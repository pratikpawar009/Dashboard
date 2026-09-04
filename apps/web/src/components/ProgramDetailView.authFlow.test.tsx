import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { getApiBaseUrl } from "@/lib/apiConfig";
import { GET as loginGET } from "@/app/login/route";
import { GET as callbackGET } from "@/app/callback/route";
import { GET as programsProxyGET } from "@/app/api/proxy/programs/route";
import { GET as programDetailProxyGET } from "@/app/api/proxy/program-detail/[program_id]/route";
import Page from "@/app/programs/[program_id]/page";
import {
  writeSession,
  SESSION_COOKIE_NAME,
  type StoredSession,
  type TokenResponse,
} from "@/lib/tokenStore";
import { ProgramDetailView } from "@/components/ProgramDetailView";
import type {
  ProgramDetailData,
  ProgramDetailHeaderData,
  ProgramSwitcherEntry,
} from "@/types/programDetail";

/**
 * AUTH-05-TC-02 -- OAuth handshake relay (`/login`, `/callback`) plus
 * dual-path bearer forwarding: a Server Component (`page.tsx`) reads the
 * session cookie directly, a Client Component (`ProgramDetailView`) proxies
 * through the Route Handler layer instead, and a `POST /auth/dev-bypass`
 * token is stored/forwarded through the identical code path as a
 * Keycloak-issued one (AC-1, AC-2, AC-3, AC-5, AC-10, AC-11).
 *
 * **ADR-0008 / D-10 note**: this story shipped full request-proxy, not
 * token-vending. One line in this TC's own `steps` field ("resolve
 * `opts.accessToken` through a mocked Route Handler") is stale wording from
 * the superseded design; `expected_results` ("sourced via the Route Handler
 * proxy, not a direct `cookies()` read") is the authoritative assertion and
 * is what this file builds against. No route here ever hands a token to
 * client-side JavaScript.
 *
 * **D-04 note**: TC-02's `steps`/`expected_results` describe `/callback`
 * 302ing to `originally_requested_page`. DECISIONS.md D-04 resolves this
 * differently and is the shipped, gate-approved contract: success always
 * lands at `/`, since Scope Out explicitly drops return-URL preservation.
 * `callback/route.ts` (already implemented) redirects to `/`, and this file
 * asserts that -- not the stale `originally_requested_page` line. Flagged
 * for human visibility in this task's return payload.
 *
 * **Shared cookie jar, deliberately not reset between tests**: `next/headers`
 * has no jsdom implementation, so it is mocked with a fake jar backed by the
 * module-scope `cookieStorage` Map below (same idiom as
 * `tokenStore.security.test.ts`'s `makeFakeCookieJar()`). Unlike that sibling
 * file, `cookieStorage` is intentionally NOT cleared in `beforeEach` here:
 * the `it()` blocks below run in declaration order (vitest's default,
 * non-concurrent) and deliberately chain through the SAME cookie -- the
 * cookie `/callback` writes is the exact cookie `POST /auth/dev-bypass`
 * overwrites, which is the exact cookie `page.tsx` and both proxy routes
 * then read. That continuity is what proves one storage path serves both
 * the server (`page.tsx`) and client (`ProgramDetailView` via the proxy)
 * call paths -- splitting these into fully independent tests would only
 * prove each half in isolation, not the shared-path claim TC-02 makes.
 *
 * **No `vi.resetModules()`**: unlike `tokenStore.test.ts` (TC-01) and
 * `tokenStore.security.test.ts` (TC-03), nothing in this file triggers a
 * token refresh -- every token fixture below carries a fresh 900s
 * `expires_in`, far outside the 60s proactive-refresh skew window, so
 * `tokenStore`'s module-level single-flight guard is never engaged and has
 * nothing to leak across steps. Plain static imports are used, matching
 * `login/route.test.ts` and `ProgramDetailView.test.tsx`.
 *
 * D-09: native `vitest` mocks only -- no MSW. `@/lib/programDetailApi.client`
 * is mocked via its `@/*` alias, matching `ProgramDetailView.test.tsx`'s own
 * (AUTH-05-retargeted) idiom; the server module `@/lib/programDetailApi` is
 * left real so `page.tsx` and the two proxy routes exercise their actual
 * FastAPI-calling code, intercepted only at the `global.fetch` boundary.
 */

const cookieStorage = new Map<string, string>();

function makeFakeCookieJar() {
  return {
    get(name: string) {
      const value = cookieStorage.get(name);
      return value === undefined ? undefined : { name, value };
    },
    set(name: string, value: string) {
      cookieStorage.set(name, value);
    },
    delete(name: string) {
      cookieStorage.delete(name);
    },
  };
}

vi.mock("next/headers", () => ({
  cookies: async () => makeFakeCookieJar(),
}));

const mockRedirect = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: (targetPath: string) => mockRedirect(targetPath),
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
}));

const fetchProgramDetailClientMock = vi.fn();
const fetchProgramsClientMock = vi.fn();

vi.mock("@/lib/programDetailApi.client", () => ({
  fetchProgramDetail: (...args: unknown[]) =>
    fetchProgramDetailClientMock(...args),
  fetchPrograms: (...args: unknown[]) => fetchProgramsClientMock(...args),
}));

// test_data fixture anchors (docs/test-cases/AUTH-05.json AUTH-05-TC-02)
const MOCKED_KEYCLOAK_URL =
  "https://lab.apexonlab.com/apexonlogin/realms/Apexon/protocol/openid-connect/auth?client_id=test&redirect_uri=http://localhost:3000/callback";
const CALLBACK_CODE = "test-auth-code";
const CALLBACK_STATE = "test-state-opaque";

const CALLBACK_SESSION_TOKENS: TokenResponse = {
  access_token: "<CALLBACK_SESSION_JWT>",
  refresh_token: "<CALLBACK_SESSION_REFRESH_JWT>",
  expires_in: 900,
};

const DEV_BYPASS_BODY = { role: "developer", email: "test@example.com" };
const DEV_BYPASS_RESPONSE: TokenResponse = {
  access_token: "<DEV_BYPASS_JWT>",
  refresh_token: "<DEV_BYPASS_REFRESH_JWT>",
  expires_in: 900,
};

const PROGRAM_DETAIL_HEADER: ProgramDetailHeaderData = {
  icon: "\u{1F3D7}",
  name: "Platform Modernization",
  type: "Migration",
  description: "Core platform upgrade",
};

const PROGRAM_DETAIL_DATA: ProgramDetailData = {
  header: PROGRAM_DETAIL_HEADER,
  summary: Array.from({ length: 7 }, (_, index) => ({
    glyph: "⬡",
    value: `${index}`,
    label: `Label ${index}`,
  })),
};

const SWITCHER_OPTIONS: ProgramSwitcherEntry[] = [
  {
    program_id: "prog-042",
    label: "Platform Modernization",
    href: "/programs/prog-042",
    dotStyle: "background-color: #0f1a2e;",
  },
  {
    program_id: "prog-099",
    label: "Growth Initiative",
    href: "/programs/prog-099",
    dotStyle: "background-color: #1f8a5b;",
  },
];

function toUrlString(input: RequestInfo | URL): string {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.toString();
  }
  return input.url;
}

/**
 * Single dispatcher for every outbound `fetch` this file's exercised code
 * makes -- routes on URL/method, matching FastAPI's documented `/auth/*`,
 * `/api/programs`, and `/api/overview/program-detail/{id}` shapes
 * (README.md § API).
 */
async function fetchDispatcher(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const url = toUrlString(input);
  const method = (init?.method ?? "GET").toUpperCase();

  if (url === `${getApiBaseUrl()}/auth/login`) {
    return new Response(null, {
      status: 302,
      headers: { location: MOCKED_KEYCLOAK_URL },
    });
  }
  if (url.startsWith(`${getApiBaseUrl()}/auth/callback`)) {
    return new Response(JSON.stringify(CALLBACK_SESSION_TOKENS), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (url === `${getApiBaseUrl()}/auth/dev-bypass` && method === "POST") {
    return new Response(JSON.stringify(DEV_BYPASS_RESPONSE), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (url.startsWith(`${getApiBaseUrl()}/api/overview/program-detail/`)) {
    return new Response(JSON.stringify(PROGRAM_DETAIL_DATA), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (url === `${getApiBaseUrl()}/api/programs`) {
    return new Response(JSON.stringify({ programs: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  throw new Error(
    `AUTH-05-TC-02 fetch mock: unexpected request ${method} ${url}`,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(fetchDispatcher);
  global.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AUTH-05-TC-02: OAuth handshake relay + dual-path bearer forwarding + dev-bypass", () => {
  it("step 1 -- GET /login redirects to the mocked Keycloak URL, never a FastAPI origin (AC-2)", async () => {
    const response = await loginGET();

    expect(response.headers.get("location")).toBe(MOCKED_KEYCLOAK_URL);
    expect(response.headers.get("location")).not.toContain(getApiBaseUrl());
    expect(fetchMock).toHaveBeenCalledWith(
      `${getApiBaseUrl()}/auth/login`,
      expect.objectContaining({ redirect: "manual" }),
    );
  });

  it("steps 2+3 -- GET /callback stores FastAPI's exact token triple via writeSession() and 302s to '/' (AC-3/AC-4, D-04); POST /auth/dev-bypass then overwrites the SAME dashboard_session cookie through the SAME writeSession() path, no dev-bypass-specific branch (AC-11)", async () => {
    const callbackRequest = new Request(
      `http://localhost:3000/callback?code=${CALLBACK_CODE}&state=${CALLBACK_STATE}`,
    );

    const callbackResponse = await callbackGET(callbackRequest);

    // D-04 (gate-approved, supersedes TC-02's stale "originally_requested_page"
    // steps line): success always lands at "/" -- Scope Out drops return-URL
    // preservation entirely.
    expect(callbackResponse.headers.get("location")).toBe(
      "http://localhost:3000/",
    );

    const storedRaw = cookieStorage.get(SESSION_COOKIE_NAME);
    expect(storedRaw).toBeDefined();
    const stored = JSON.parse(storedRaw as string) as StoredSession;
    expect(stored.accessToken).toBe(CALLBACK_SESSION_TOKENS.access_token);
    expect(stored.refreshToken).toBe(CALLBACK_SESSION_TOKENS.refresh_token);

    // Step 3: mint via a mocked POST /auth/dev-bypass (no frontend route
    // wraps this endpoint in this story -- it is called directly against
    // FastAPI, same as a developer/test harness would), then store the
    // result through the EXACT same `writeSession()` import `/callback`
    // itself just used above -- proving there is no dev-bypass-specific
    // branch anywhere in storage or forwarding.
    const devBypassResponse = await fetch(
      `${getApiBaseUrl()}/auth/dev-bypass`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(DEV_BYPASS_BODY),
      },
    );
    const devBypassTokens = (await devBypassResponse.json()) as TokenResponse;
    await writeSession(devBypassTokens);

    const overwrittenRaw = cookieStorage.get(SESSION_COOKIE_NAME);
    const overwritten = JSON.parse(overwrittenRaw as string) as StoredSession;
    expect(overwritten.accessToken).toBe(DEV_BYPASS_RESPONSE.access_token);
    expect(overwritten.refreshToken).toBe(DEV_BYPASS_RESPONSE.refresh_token);
  });

  it("step 4 -- page.tsx's server-side fetchProgramDetail call attaches Authorization: Bearer <DEV_BYPASS_JWT> sourced directly from the cookie (AC-5, server path)", async () => {
    // dashboard_session now holds the dev-bypass session the previous test
    // wrote -- this cross-test continuity is deliberate (see file header).
    await Page({ params: Promise.resolve({ program_id: "prog-042" }) });

    expect(fetchMock).toHaveBeenCalledWith(
      `${getApiBaseUrl()}/api/overview/program-detail/prog-042`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${DEV_BYPASS_RESPONSE.access_token}`,
        }),
      }),
    );
  });

  it("step 5 -- both proxy routes attach the identical Authorization: Bearer <DEV_BYPASS_JWT> on their own server-to-server call to FastAPI (AC-10, client path's server half)", async () => {
    const programsResponse = await programsProxyGET();
    expect(programsResponse.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      `${getApiBaseUrl()}/api/programs`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${DEV_BYPASS_RESPONSE.access_token}`,
        }),
      }),
    );

    const detailRequest = new Request(
      "http://localhost:3000/api/proxy/program-detail/prog-042",
    );
    const detailResponse = await programDetailProxyGET(detailRequest, {
      params: Promise.resolve({ program_id: "prog-042" }),
    });
    expect(detailResponse.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      `${getApiBaseUrl()}/api/overview/program-detail/prog-042`,
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${DEV_BYPASS_RESPONSE.access_token}`,
        }),
      }),
    );
  });

  it("step 6 -- ProgramDetailView's browser-visible calls into programDetailApi.client never carry an access token, Authorization header, or any token value (negative, client path's browser half)", async () => {
    fetchProgramsClientMock.mockResolvedValue(SWITCHER_OPTIONS);
    fetchProgramDetailClientMock.mockResolvedValue({
      status: "ok",
      data: PROGRAM_DETAIL_DATA,
    });

    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={{ status: "ok", data: PROGRAM_DETAIL_DATA }}
      />,
    );

    await waitFor(() =>
      expect(fetchProgramsClientMock).toHaveBeenCalledTimes(1),
    );
    // fetchPrograms() takes no parameters at all -- there is no slot for a token.
    expect(fetchProgramsClientMock.mock.calls[0]).toEqual([]);

    fireEvent.click(
      screen.getByRole("button", { name: /Platform Modernization/ }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: /Growth Initiative/ }),
    );

    await waitFor(() =>
      expect(fetchProgramDetailClientMock).toHaveBeenCalledWith("prog-099", {
        switchedFrom: "prog-042",
      }),
    );

    const allClientCallArgs = [
      ...fetchProgramsClientMock.mock.calls,
      ...fetchProgramDetailClientMock.mock.calls,
    ];
    const serializedArgs = JSON.stringify(allClientCallArgs);
    expect(serializedArgs).not.toContain("Authorization");
    expect(serializedArgs).not.toContain("accessToken");
    expect(serializedArgs).not.toContain(DEV_BYPASS_RESPONSE.access_token);

    // The client module is fully mocked in this test -- no real request ever
    // left this "browser" (jsdom) for a token to ride along on.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("structural check -- neither ProgramDetailView.tsx nor programDetailApi.client.ts reference next/headers, cookies(, or tokenStore", () => {
    const currentDir = path.dirname(fileURLToPath(import.meta.url));
    const componentSource = readFileSync(
      path.join(currentDir, "ProgramDetailView.tsx"),
      "utf-8",
    );
    const clientApiSource = readFileSync(
      path.join(currentDir, "..", "lib", "programDetailApi.client.ts"),
      "utf-8",
    );

    for (const source of [componentSource, clientApiSource]) {
      // Both files' own docstrings legitimately reference `next/headers` and
      // `tokenStore.callWithAuth` in prose when explaining the proxy
      // boundary they deliberately stay outside of -- so these checks target
      // the actual import specifiers, not the bare words, to avoid a false
      // positive on that prose.
      expect(source).not.toContain('from "next/headers"');
      expect(source).not.toContain("cookies(");
      expect(source).not.toContain('from "@/lib/tokenStore"');
    }
  });
});
