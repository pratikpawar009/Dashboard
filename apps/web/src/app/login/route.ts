import { NextResponse } from "next/server";
import { getApiBaseUrl } from "@/lib/apiConfig";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * `GET /login` -- server-to-server relay to FastAPI `GET /auth/login`
 * (AUTH-05-AC-2, DATA-DESIGN.md § 9). Top-level `/login`, not nested under
 * `/api/auth/` (REQUIREMENTS.md FR-3): `OIDC_REDIRECT_URI` must exact-match
 * this path.
 *
 * The browser must end up on Keycloak's own authorization URL, never on a
 * FastAPI origin (AC-2) -- so `redirect: "manual"` is required here: without
 * it, `fetch` would follow FastAPI's `302` itself, server-to-server, and
 * this handler would never see a `Location` header to relay back to the
 * browser. With it, FastAPI's `302` is observable as a plain response with
 * a `location` header, which is read case-insensitively (the Headers API is
 * already case-insensitive) and handed to `NextResponse.redirect`.
 *
 * FastAPI returns `501` while the `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` /
 * `OIDC_ISSUER` triple is incomplete (README.md "Keycloak client
 * requirements") -- a fresh local checkout with OIDC unconfigured hits this
 * path and gets the generic 502 below, not a raw 501. That is expected.
 *
 * Failure handling is uniform and opaque: a missing `Location`, any
 * non-3xx status (the documented 501 included), or a thrown/timed-out
 * fetch all produce the same generic 502 plain-text response -- FastAPI's
 * status text or body is never surfaced to the browser.
 *
 * No `tokenStore` import: this handshake runs before any session exists,
 * so there is no cookie to read or write here.
 */
export async function GET(): Promise<NextResponse> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/auth/login`, {
      redirect: "manual",
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

    if (response.status < 300 || response.status >= 400) {
      return new NextResponse("Sign-in is unavailable.", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      });
    }

    const location = response.headers.get("location");
    if (!location) {
      return new NextResponse("Sign-in is unavailable.", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      });
    }

    return NextResponse.redirect(location);
  } catch {
    return new NextResponse("Sign-in is unavailable.", {
      status: 502,
      headers: { "Content-Type": "text/plain" },
    });
  }
}
