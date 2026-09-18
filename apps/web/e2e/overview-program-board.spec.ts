import { test, expect, type Page } from "@playwright/test";

/**
 * E2E: `/overview` boots without an RSC "Event handlers cannot be passed to
 * Client Component props" error (regression-OVW-04-TC-06).
 *
 * ## Why this exists — root cause
 *
 * `ProgramCard.tsx` (a Server Component) used to attach `onClick` directly
 * to its root `<a>`, with no `"use client"` boundary anywhere in its
 * ancestor chain (`ProgramLeaderboard.tsx`, `AdoptionOverview.tsx`,
 * `app/overview/page.tsx`). Next.js App Router raises "Event handlers
 * cannot be passed to Client Component props" for that shape, so the real
 * `/overview` page 500'd for every persona in the actually-running app —
 * even though `ProgramCard.test.tsx`'s vitest/jsdom unit tests (which
 * mount the component directly, bypassing the RSC serialization boundary
 * entirely) never caught it and kept passing throughout.
 *
 * The fix extracted the interactive click (D-06's `program_drilldown`
 * telemetry) into `ProgramCardLink.tsx`, a small `"use client"` leaf, while
 * `ProgramCard` itself stays a Server Component — see that file's doc
 * comment.
 *
 * ## Why this boundary, not vitest/jsdom
 *
 * The defect is a Next.js RSC serialization-boundary violation, which only
 * exists when the App Router actually renders the real component tree
 * server-side. vitest/jsdom mounts `<ProgramCard>` directly with React DOM
 * client-side rendering, never invoking Next's RSC payload
 * serialization — so no unit test in this file's neighbourhood is capable
 * of catching this class of defect, regression or otherwise. Playwright,
 * driven against a real `next dev`/`next build` server (`playwright.config.ts`
 * `webServer`), is the only boundary in this repo that exercises that
 * serialization step.
 *
 * ## DEFERRED EXECUTION — read before running
 *
 * Matches `program-token-trend.spec.ts`'s documented pattern: at author
 * time (`/arh-implement`) only `playwright test --list` is executed — a
 * dry-run that parses this file and confirms Playwright's config picks it
 * up. Actual execution (a running API + seeded `program_roster` data so
 * `GET /api/overview/summary` and the program board have at least one row)
 * is deferred to `/arh-validate-feature`, same preconditions as that spec.
 */

async function signInAsDeveloper(page: Page, webBaseUrl: string) {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const response = await page.request.post(`${apiBaseUrl}/auth/dev-bypass`, {
    data: { role: "developer" },
  });
  expect(
    response.ok(),
    "POST /auth/dev-bypass must be reachable and return 200 — see file header for required ENVIRONMENT allow-list",
  ).toBeTruthy();
  const tokens = (await response.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };

  const storedSession = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
  };

  const baseUrl = new URL(webBaseUrl);
  await page.context().addCookies([
    {
      name: "dashboard_session",
      value: JSON.stringify(storedSession),
      domain: baseUrl.hostname,
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
}

test.describe("Overview — program board renders without an RSC event-handler crash (regression-OVW-04-TC-06)", () => {
  test.beforeEach(async ({ page, baseURL }) => {
    await signInAsDeveloper(page, baseURL ?? "http://localhost:3000");
  });

  test("GET /overview returns 200 and renders at least one program card link", async ({
    page,
  }) => {
    const response = await page.goto("/overview");

    expect(
      response?.status(),
      "the real Next.js server must not 500 rendering ProgramCard's event handler across an RSC boundary",
    ).toBe(200);

    // The program board section renders; each card is a real, keyboard
    // reachable <a> (ProgramCardLink) — proof the client leaf mounted and
    // hydrated rather than the page failing before it got there.
    await expect(page.getByText("Program board")).toBeVisible();
    const firstCardLink = page
      .locator('a[aria-label$="open program detail"]')
      .first();
    await expect(firstCardLink).toBeVisible();
    await expect(firstCardLink).toHaveAttribute("href", /^\/programs\//);
  });
});
