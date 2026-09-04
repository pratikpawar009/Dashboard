import { NextResponse } from "next/server";

import { fetchPrograms } from "@/lib/programDetailApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/programs` -- full server-to-server proxy for
 * `GET /api/programs` (ADR-0008 / DECISIONS.md D-09/D-10). The browser never
 * reaches FastAPI directly for this call: this Route Handler resolves the
 * `dashboard_session` cookie's access token server-side via
 * `tokenStore.callWithAuth()` (which itself calls `getValidAccessToken()`,
 * proactively refreshing within the 60s skew), calls the server-side
 * `fetchPrograms()` (`programDetailApi.ts`, unchanged FastAPI-calling shape),
 * and returns the result as JSON. The raw access token never leaves this
 * Node process -- it is attached to the outbound FastAPI request only and
 * never appears in this route's response body or in any header the browser
 * can read (NFR-security, TC-03).
 *
 * The `isUnauthorized` predicate passed to `callWithAuth()` is `() => false`,
 * deliberately -- `fetchPrograms()` degrades to `[]` on ANY failure,
 * including a 401, and never signals `unauthorized` (see its own docstring).
 * There is therefore nothing here for `callWithAuth()`'s reactive 401
 * retry-once to detect; what this route actually gets from the wrapper is
 * `getValidAccessToken()`'s proactive 60s-skew refresh. Do not "fix" this
 * predicate to inspect the resolved array -- there is no failure signal in
 * it to inspect.
 *
 * A caught `SessionExpiredError` (the refresh itself failed unrecoverably)
 * maps to `401 {error: "session_expired"}`. Any other throw maps to a
 * generic `502 {error: "upstream_error"}` -- neither branch surfaces a raw
 * error message or an upstream response body to the browser.
 */
export async function GET(): Promise<NextResponse> {
  try {
    const programs = await callWithAuth(
      (accessToken) => fetchPrograms({ accessToken }),
      () => false,
    );
    return NextResponse.json({ programs });
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      return NextResponse.json({ error: "session_expired" }, { status: 401 });
    }
    return NextResponse.json({ error: "upstream_error" }, { status: 502 });
  }
}
