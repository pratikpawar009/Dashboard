import { NextResponse } from "next/server";
import { getApiBaseUrl } from "@/lib/apiConfig";
import { clearSession, readSession } from "@/lib/tokenStore";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait. Matches `login/route.ts`'s
 * `FETCH_TIMEOUT_MS` precedent.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * `GET /logout` -- server-to-server relay to FastAPI `GET /auth/logout`
 * (AUTH-07-FR-5, DECISIONS.md D-08). No visible entry point anywhere in the
 * UI (AC-15) -- reachable only by direct URL navigation; this file is the
 * entire deliverable, no mockup or component is touched.
 *
 * Call order is fixed by D-08 and is NOT reorderable:
 *
 *   1. `readSession()` FIRST -- captures the still-valid, not-yet-cleared
 *      access token before anything clears it.
 *   2. `clearSession()` -- clears the `dashboard_session` cookie (AC-8:
 *      before relaying any redirect). Called unconditionally, even when no
 *      prior session exists (idempotent), and never skipped -- the relay
 *      below must never short-circuit ahead of it.
 *   3. `fetch` `GET /auth/logout` carrying the JUST-READ, pre-clear access
 *      token as `Authorization: Bearer <accessToken>`. Clearing the cookie
 *      does not invalidate the token value itself (AC-16: an issued access
 *      token survives cookie-clear until its own expiry) -- forwarding it is
 *      how the backend's `dashboard_logout` event resolves a `user_id`
 *      instead of always logging `"unknown"`.
 *   4. Relay the returned `302`'s `Location` header to the browser.
 *
 * Getting this order wrong (e.g. clearing before reading, or fetching before
 * clearing) means `dashboard_logout` always logs `user_id="unknown"` -- the
 * observable symptom of a reordering regression.
 *
 * `redirect: "manual"` is required for the same reason `login/route.ts`
 * needs it: without it, `fetch` would follow FastAPI's `302` itself,
 * server-to-server, and this handler would never see a `Location` header to
 * relay back to the browser.
 *
 * Failure handling mirrors `login/route.ts` exactly: a missing `Location`,
 * any non-3xx status (including the documented `501` when OIDC config or
 * `frontend_login_url` is incomplete), or a thrown/timed-out fetch all
 * produce the same generic `502` plain-text response -- FastAPI's status
 * text or body is never surfaced to the browser.
 *
 * No shipped route is modified by this file (AC-9) -- `/login`, `/callback`,
 * `/api/proxy/*` all stay untouched.
 */
export async function GET(): Promise<NextResponse> {
  const session = await readSession();
  await clearSession();

  try {
    const response = await fetch(`${getApiBaseUrl()}/auth/logout`, {
      redirect: "manual",
      headers: session
        ? { Authorization: `Bearer ${session.accessToken}` }
        : {},
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

    if (response.status < 300 || response.status >= 400) {
      return new NextResponse("Sign-out is unavailable.", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      });
    }

    const location = response.headers.get("location");
    if (!location) {
      return new NextResponse("Sign-out is unavailable.", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      });
    }

    return NextResponse.redirect(location);
  } catch {
    return new NextResponse("Sign-out is unavailable.", {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    });
  }
}
