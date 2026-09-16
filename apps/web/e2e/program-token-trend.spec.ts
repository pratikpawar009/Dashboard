import { test, expect, type Page } from "@playwright/test";

/**
 * E2E: Program Detail range-toggle flow (PGD-02-TC-01, e2e half).
 *
 * Covers PGD-02-AC-1/AC-5: the Daily Token Consumption chart
 * (`DailyTokenTrendChart`, T-12) renders with the default 30D range on
 * load, and toggling to 7D/90D refreshes the chart with `aria-pressed`
 * tracking the active toggle.
 *
 * ## DEFERRED EXECUTION — read before running
 *
 * Per `docs/features/PGD-02/PLAN.md` §7 Test Strategy, this spec's actual
 * *run* is deferred to `/arh-validate-feature`. At author time
 * (`/arh-implement`) only `playwright test --list` is executed — a dry-run
 * that parses this file and confirms Playwright's config picks it up. There
 * is no running API/DB in this session, and `playwright install` has not
 * been run, so no browser is launched here.
 *
 * `/arh-validate-feature` MUST provide, before this spec can actually pass:
 *
 * 1. A running API (`services/api`) reachable at the URL
 *    `apps/web/.env` / `NEXT_PUBLIC_API_URL` resolves to, and a running web
 *    dev server (`playwright.config.ts`'s `webServer` already starts
 *    `pnpm dev` against `http://localhost:3000` — no extra step needed for
 *    the frontend process itself).
 * 2. `ENVIRONMENT` resolved to one of `local|development|dev|test|ci` on the
 *    API so `POST /auth/dev-bypass` is registered (see `CLAUDE.md` /
 *    `README.md` — the route 404s outside that allow-list).
 * 3. A seeded program with id `SEED_PROGRAM_ID` (below) that exists and is
 *    visible to `GET /api/overview/program-detail/{program_id}` (any
 *    authenticated persona — this endpoint is an open aggregate, no
 *    per-program RBAC scoping per PGD-02-AC-7 / TC-14 / TC-15).
 * 4. `program_token_series` rows for `SEED_PROGRAM_ID` covering at least the
 *    trailing 90 calendar days, so all three range toggles (7D/30D/90D)
 *    return non-degenerate series. Gaps are fine — PGD-02-AC-3 zero-pads
 *    missing days — but at least one non-zero day in each window keeps the
 *    chart's `aria-label` token total assertion meaningful.
 * 5. Network reachability from the Playwright browser context to both the
 *    web dev server and (transitively, via the web app's `/api/proxy/*`
 *    route handlers, ADR-0008) the API — no additional CORS config is
 *    needed since the browser only ever talks to the same-origin web app.
 */

const SEED_PROGRAM_ID = "PROG-100";

/**
 * Logs in via `POST /auth/dev-bypass` (documented local/dev/test/ci-only
 * mechanism, see `CLAUDE.md` and `README.md`) and seeds the browser
 * context's `dashboard_session` cookie directly, matching the exact shape
 * `tokenStore.ts`'s `StoredSession`/`persistTokens()` writes
 * (`apps/web/src/lib/tokenStore.ts:72-77,128-139`) — `{accessToken,
 * refreshToken, expiresAt}`, httpOnly, `sameSite: "lax"`, `path: "/"`.
 *
 * This is the minimum-viable approach for this repo's first Playwright
 * spec: there is no existing e2e auth helper to reuse. Writing the cookie
 * directly (rather than driving the OIDC/dev-bypass UI flow through
 * `/login`) keeps the spec focused on the range-toggle behavior under test
 * rather than re-testing the login flow, which has its own coverage
 * elsewhere (AUTH-05 stories).
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

test.describe("Program Detail — daily token consumption range toggle (TC-01)", () => {
  test.beforeEach(async ({ page, baseURL }) => {
    await signInAsDeveloper(page, baseURL ?? "http://localhost:3000");
  });

  test("defaults to 30D on load, then toggles to 7D and 90D", async ({
    page,
  }) => {
    await page.goto(`/programs/${SEED_PROGRAM_ID}`);

    const toggleGroup = page.getByRole("group", {
      name: "Select date range for daily token consumption",
    });
    const chart = page.getByRole("img", { name: /Daily token usage trend/ });

    // AC-1: default range is 30D — the 30D toggle starts pressed, the chart
    // renders, and its accessible name reports a 30-day series.
    const toggle30d = toggleGroup.getByRole("button", { name: "30D" });
    const toggle7d = toggleGroup.getByRole("button", { name: "7D" });
    const toggle90d = toggleGroup.getByRole("button", { name: "90D" });

    await expect(toggle30d).toHaveAttribute("aria-pressed", "true");
    await expect(toggle7d).toHaveAttribute("aria-pressed", "false");
    await expect(toggle90d).toHaveAttribute("aria-pressed", "false");
    await expect(chart).toBeVisible();
    await expect(chart).toHaveAccessibleName(
      /Daily token usage trend, 30 days,/,
    );

    // AC-5: toggling to 7D refreshes the chart and flips aria-pressed.
    await toggle7d.click();
    await expect(toggle7d).toHaveAttribute("aria-pressed", "true");
    await expect(toggle30d).toHaveAttribute("aria-pressed", "false");
    await expect(chart).toHaveAccessibleName(
      /Daily token usage trend, 7 days,/,
    );

    // AC-5: toggling to 90D refreshes the chart and flips aria-pressed again.
    await toggle90d.click();
    await expect(toggle90d).toHaveAttribute("aria-pressed", "true");
    await expect(toggle7d).toHaveAttribute("aria-pressed", "false");
    await expect(chart).toHaveAccessibleName(
      /Daily token usage trend, 90 days,/,
    );
  });
});
