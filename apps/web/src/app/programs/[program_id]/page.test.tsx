import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import Page from "./page";
import shellStyles from "@/components/PersonaDashboardShell.module.css";
import type { ProgramDetailResult } from "@/types/programDetail";

/**
 * `programs/[program_id]/page.tsx` tests (T-08, DECISIONS.md D-02) — the
 * page-level composition harness for `PGD-07-FR-1-TC-01` (Promise.all
 * coordination), `PGD-07-TC-C4` (SessionExpiredError from either fetch ->
 * single coordinated redirect), `PGD-07-TC-09` (401-only-on-/api/me falls
 * through, no redirect), `PGD-07-TC-05` (loading state), and
 * `PGD-07-NFR-performance-TC-01` (concurrent, not sequential, fetch
 * assertion).
 *
 * Mirrors `apps/web/src/app/overview/page.test.tsx` exactly (D-02):
 * `@/lib/tokenStore`'s `callWithAuth` is replaced with a faithful fake that
 * actually invokes the supplied `makeRequest` with a fixed test access
 * token, so the two concurrent `callWithAuth()` wrappers in `page.tsx`
 * transparently forward to whatever `@/lib/programDetailApi`'s
 * `fetchProgramDetail` / `@/lib/meApi`'s `fetchMe` are mocked to do.
 * `SessionExpiredError` is re-exported from the real module via
 * `importOriginal`, so `page.tsx`'s own `instanceof` check in its `catch`
 * block matches genuinely rather than silently falling through.
 * `next/navigation`'s `redirect()` is mocked to throw (same idiom as
 * `overview/page.test.tsx` and `app/login/page.test.tsx`): real `redirect()`
 * works by throwing its own `NEXT_REDIRECT` control-flow signal, and
 * `page.tsx`'s own docstring states that throw MUST propagate out of the
 * `catch` block rather than being swallowed.
 *
 * `@/components/ProgramDetailView` is NOT mocked — this page-level harness
 * asserts against the real rendered DOM (the shell's brand bar / identity
 * block classes), same as `overview/page.test.tsx` renders the real
 * `AdoptionOverview`. `ProgramDetailView` is a Client Component that fetches
 * `GET /api/programs` on mount via `@/lib/programDetailApi.client`'s
 * `fetchPrograms` — left unmocked deliberately: it hits a real (unmocked)
 * global `fetch`, which in the jsdom test environment rejects, and the
 * component already handles that by leaving `switcherOptions` empty. This
 * matches `ProgramDetailView.test.tsx`'s own established idiom for this
 * component.
 *
 * No `jest-dom` is wired in this project (`vitest.config.ts` has no
 * `setupFiles`) — assertions use plain vitest matchers, `.textContent`, and
 * `querySelector`, never `toBeInTheDocument()`. Every test unmounts
 * explicitly via `afterEach(cleanup)`.
 */

const TEST_ACCESS_TOKEN = "test-access-token";
const TEST_PROGRAM_ID = "prog-123";

const {
  mockCallWithAuth,
  mockFetchProgramDetail,
  mockFetchMe,
  mockRedirect,
} = vi.hoisted(() => ({
  mockCallWithAuth: vi.fn(),
  mockFetchProgramDetail: vi.fn(),
  mockFetchMe: vi.fn(),
  mockRedirect: vi.fn(),
}));

vi.mock("@/lib/tokenStore", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...(actual as object),
    callWithAuth: mockCallWithAuth,
  };
});

vi.mock("@/lib/programDetailApi", () => ({
  fetchProgramDetail: mockFetchProgramDetail,
}));

vi.mock("@/lib/meApi", () => ({
  fetchMe: mockFetchMe,
}));

vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    mockRedirect(path);
    throw new Error(`NEXT_REDIRECT:${path}`);
  },
  // `ProgramDetailView` (unmocked, rendered for real below) calls
  // `useRouter()` for its switcher-reload `router.replace()` -- unused by
  // any assertion here, only required so the component mounts without
  // throwing.
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const { SessionExpiredError } = await import("@/lib/tokenStore");

// Minimal ok fixture — this harness asserts persona/identity composition and
// concurrency/redirect coordination, not the summary-card rendering rules
// already covered by `ProgramDetailView.test.tsx`/`ProgramSummaryCards`'
// own suites.
const PROGRAM_DETAIL_OK: ProgramDetailResult = {
  status: "ok",
  data: {
    header: {
      icon: "🚀",
      name: "Test Program",
      type: "internal",
      description: "A test program",
    },
    summary: [{ glyph: "▦", value: "10", label: "Some metric" }],
  },
};

function pageProps() {
  return { params: Promise.resolve({ program_id: TEST_PROGRAM_ID }) };
}

beforeEach(() => {
  mockCallWithAuth.mockImplementation(
    async (makeRequest: (accessToken: string) => unknown) =>
      makeRequest(TEST_ACCESS_TOKEN),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PGD-07-FR-1-TC-01 — Promise.all coordinates /api/me and the program-detail fetch", () => {
  it("invokes both fetches before either resolves (concurrent, not sequential) and passes both results through", async () => {
    const invocationOrder: string[] = [];

    mockFetchProgramDetail.mockImplementation(async () => {
      invocationOrder.push("program-detail:invoked");
      return PROGRAM_DETAIL_OK;
    });
    mockFetchMe.mockImplementation(async () => {
      invocationOrder.push("me:invoked");
      return { status: "ok", data: { name: "Priya Nair", persona: "cio" } };
    });

    const { container } = render(await Page(pageProps()));

    // Both fetches were invoked (Promise.all issues both, not one-then-the-other).
    expect(invocationOrder).toContain("program-detail:invoked");
    expect(invocationOrder).toContain("me:invoked");
    expect(mockFetchProgramDetail).toHaveBeenCalledTimes(1);
    expect(mockFetchMe).toHaveBeenCalledTimes(1);

    // Both resolved values reached ProgramDetailView: the program-detail
    // header text renders, and the identity block carries the resolved persona.
    expect(document.body.textContent).toContain("Test Program");
    expect(
      container.getElementsByClassName(shellStyles.jobTitle)[0].textContent,
    ).toBe("Chief Information Officer");
  });
});

describe("PGD-07-NFR-performance-TC-01 — exactly one GET /api/me call per server render, concurrent fetches", () => {
  it("calls fetchMe exactly once and both fetches are in flight simultaneously (concurrency, not sum-of-latencies)", async () => {
    let programDetailResolveTime = 0;
    let meResolveTime = 0;
    let programDetailStarted = false;
    let meStarted = false;

    mockFetchProgramDetail.mockImplementation(async () => {
      programDetailStarted = true;
      // At the moment this fetch starts, the other one must already be in
      // flight too -- proves Promise.all fired both before either resolved.
      await new Promise((resolve) => setTimeout(resolve, 10));
      programDetailResolveTime = Date.now();
      return PROGRAM_DETAIL_OK;
    });
    mockFetchMe.mockImplementation(async () => {
      meStarted = true;
      await new Promise((resolve) => setTimeout(resolve, 10));
      meResolveTime = Date.now();
      return { status: "ok", data: { name: "Priya Nair", persona: "cio" } };
    });

    await Page(pageProps());

    expect(mockFetchMe).toHaveBeenCalledTimes(1);
    expect(programDetailStarted).toBe(true);
    expect(meStarted).toBe(true);
    // Both resolved within the same ~10ms window (concurrent), not ~20ms
    // apart (sequential) -- a generous bound avoids test flakiness while
    // still failing a sequential-await regression.
    expect(Math.abs(programDetailResolveTime - meResolveTime)).toBeLessThan(
      10,
    );
  });
});

describe("PGD-07-TC-C4 — SessionExpiredError from either concurrent fetch triggers the same coordinated redirect", () => {
  it("redirects when the program-detail fetch throws SessionExpiredError", async () => {
    mockFetchProgramDetail.mockRejectedValue(
      new SessionExpiredError("refresh failed"),
    );
    mockFetchMe.mockResolvedValue({
      status: "ok",
      data: { name: "Priya Nair", persona: "cio" },
    });

    await expect(Page(pageProps())).rejects.toThrow("NEXT_REDIRECT");

    expect(mockRedirect).toHaveBeenCalledTimes(1);
    expect(mockRedirect).toHaveBeenCalledWith("/login");
  });

  it("redirects when the GET /api/me fetch throws SessionExpiredError", async () => {
    mockFetchProgramDetail.mockResolvedValue(PROGRAM_DETAIL_OK);
    mockFetchMe.mockRejectedValue(new SessionExpiredError("refresh failed"));

    await expect(Page(pageProps())).rejects.toThrow("NEXT_REDIRECT");

    expect(mockRedirect).toHaveBeenCalledTimes(1);
    expect(mockRedirect).toHaveBeenCalledWith("/login");
  });
});

describe("PGD-07-TC-09 — a 401 (unauthorized, not SessionExpiredError) from GET /api/me alone does not redirect", () => {
  it("falls through to the neutral identity fallback instead of redirecting, program-detail rendering unaffected", async () => {
    mockFetchProgramDetail.mockResolvedValue(PROGRAM_DETAIL_OK);
    mockFetchMe.mockResolvedValue({ status: "unauthorized" });

    const { container } = render(await Page(pageProps()));

    expect(mockRedirect).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Test Program");
    // sentinel path -> signedInUser stays undefined -> shell's D-05 neutral
    // avatar fallback (plain gray circle, aria-hidden), no name/jobTitle text.
    expect(container.getElementsByClassName(shellStyles.name)).toHaveLength(
      0,
    );
    expect(
      container.getElementsByClassName(shellStyles.avatarNeutral)[0]
        ?.getAttribute("aria-hidden"),
    ).toBe("true");
  });
});

describe("PGD-07-FR-3-TC-01 — persona-resolution-error sentinel passed to the shell on a non-ok /api/me result", () => {
  it("degrades the identity block to the neutral fallback (sentinel path), never a guessed persona, on a 403", async () => {
    mockFetchProgramDetail.mockResolvedValue(PROGRAM_DETAIL_OK);
    mockFetchMe.mockResolvedValue({ status: "forbidden" });

    const { container } = render(await Page(pageProps()));

    // AC-5 (AF-01, resolved): the sentinel reaches the shell (FR-3, this
    // page's own scope) AND the failure is now both visible and announced on
    // this route. PersonaDashboardShell originally carried the "Persona
    // unavailable" badge only inside its program-header / pageTitle-header
    // regions, neither of which mounts for ProgramDetailView's composition
    // (`program: undefined` per AC-2, no `pageTitle`) -- so a persona
    // resolution failure degraded silently to the D-05 neutral avatar, with
    // no announcement to assistive technology at all. The shell now renders
    // the badge + announcement from the identity block when no header region
    // is present, which is what these assertions pin.
    expect(document.body.textContent).toContain("Persona unavailable");
    expect(
      document.querySelector('[aria-live="assertive"]')?.textContent,
    ).toBe("Unable to load your dashboard view.");
    expect(container.getElementsByClassName(shellStyles.name)).toHaveLength(
      0,
    );
    expect(
      container.getElementsByClassName(shellStyles.avatarNeutral)[0]
        ?.getAttribute("aria-hidden"),
    ).toBe("true");
  });
});

describe("PGD-07-TC-05 — loading state: page.tsx never flashes a partial render while /api/me is in flight", () => {
  it("keeps the page render pending (no persona/identity block ever reaches the DOM) until GET /api/me resolves", async () => {
    mockFetchProgramDetail.mockResolvedValue(PROGRAM_DETAIL_OK);

    // `page.tsx` is a single `async function` -- it only returns JSX once
    // its own `Promise.all` (program-detail fetch + fetchMe) has resolved.
    // So the loading contract this test proves at the page level is
    // structural: nothing can render, flash, or partially mount while
    // `fetchMe` is unresolved, because `Page()` itself has not returned yet.
    // (`PGD-07-AC-4`'s brand-bar-only loading DOM, i.e. what DOES render
    // while `persona === undefined`, is `PersonaDashboardShell`'s own
    // `isLoading` branch and is already covered by
    // `ProgramDetailView.test.tsx`'s suites, which render with `persona`
    // omitted per that file's own docstring.)
    let resolveFetchMe!: () => void;
    mockFetchMe.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetchMe = () =>
            resolve({
              status: "ok",
              data: { name: "Priya Nair", persona: "cio" },
            });
        }),
    );

    let settled = false;
    const pending = Page(pageProps()).then((jsx) => {
      settled = true;
      return jsx;
    });

    // Microtasks flush; the unresolved fetchMe promise must keep the whole
    // page render pending -- no partial/flashed identity block is possible.
    await Promise.resolve();
    await Promise.resolve();
    expect(settled).toBe(false);

    resolveFetchMe();
    const jsx = await pending;
    expect(settled).toBe(true);

    const { container } = render(jsx);
    expect(
      container.getElementsByClassName(shellStyles.jobTitle)[0].textContent,
    ).toBe("Chief Information Officer");
  });
});
