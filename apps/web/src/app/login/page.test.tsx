import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import Page from "./page";
import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";
import type { StoredSession } from "@/lib/tokenStore";

/**
 * `login/page.tsx` tests (T-12) — AC-16/AC-17/AC-18/AC-19 + OVW-05-TC-02
 * (`docs/test-cases/OVW-05.json`).
 *
 * `readSession()` (`@/lib/tokenStore`) and `redirect()` (`next/navigation`)
 * are both mocked. `page.tsx` is an async Server Component with no route
 * params, rendered here via `await Page()` — the same idiom
 * `ProgramDetailView.authFlow.test.tsx` and `overview/page.tsx`'s sibling
 * Server Components use.
 *
 * `redirect()`'s mock **throws** rather than returning normally, matching
 * `page.tsx`'s own docstring: real `next/navigation` `redirect()` works by
 * throwing its own `NEXT_REDIRECT` control-flow signal. `page.tsx` calls
 * `redirect()` with no `return` following it in the same `if` block — a
 * non-throwing mock (the shape `ProgramDetailView.authFlow.test.tsx` uses,
 * where only `redirect()`'s call arguments matter) would let execution fall
 * through to the sign-in card below it, silently defeating OVW-05-TC-02's
 * "no sign-in markup renders" assertion. Because the mock throws, `Page()`'s
 * returned promise rejects and the sign-in card is provably never
 * constructed — there is nothing to render, so `queryByRole` correctly finds
 * nothing in an untouched DOM.
 *
 * No `jest-dom` matchers are wired in this project (`AdoptionOverview.test.tsx`,
 * `PersonaDashboardShell.test.tsx`) — assertions use plain vitest matchers and
 * `.textContent`, not `toBeInTheDocument()`. `vitest.config.ts` has no
 * `setupFiles`, so Testing Library's auto-cleanup is not wired — each test
 * unmounts explicitly via `afterEach(cleanup)`.
 */

const mockReadSession = vi.fn();
const mockRedirect = vi.fn();

vi.mock("@/lib/tokenStore", () => ({
  readSession: () => mockReadSession(),
}));

vi.mock("next/navigation", () => ({
  redirect: (path: string) => {
    mockRedirect(path);
    throw new Error(`NEXT_REDIRECT:${path}`);
  },
}));

const VALID_SESSION: StoredSession = {
  accessToken: "<ACCESS_TOKEN>",
  refreshToken: "<REFRESH_TOKEN>",
  expiresAt: Date.now() + 900_000,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("OVW-05-TC-02 — already-authenticated pass-through (AC-18)", () => {
  it("redirects to /overview before any sign-in markup renders; 'Sign in with SSO' is never shown", async () => {
    mockReadSession.mockResolvedValue(VALID_SESSION);

    await expect(Page()).rejects.toThrow("NEXT_REDIRECT");

    expect(mockRedirect).toHaveBeenCalledTimes(1);
    expect(mockRedirect).toHaveBeenCalledWith(ADOPTION_OVERVIEW_ROUTE);
    expect(
      screen.queryByRole("button", { name: "Sign in with SSO" }),
    ).toBeNull();
  });
});

describe("Unauthenticated visitor (AC-16/AC-17/AC-19)", () => {
  it("renders the brand-bar identity: product name + tagline (AC-16), and never redirects", async () => {
    mockReadSession.mockResolvedValue(null);

    render(await Page());

    expect(screen.getByText("AgentRise Harness").textContent).toBe(
      "AgentRise Harness",
    );
    expect(screen.getByText("AI SDLC Governance").textContent).toBe(
      "AI SDLC Governance",
    );
    expect(mockRedirect).not.toHaveBeenCalled();
  });

  it("exposes exactly one focusable element — the SSO action, its visible text as the sole accessible name, no aria-label override (AC-17)", async () => {
    mockReadSession.mockResolvedValue(null);

    render(await Page());

    expect(screen.getAllByRole("button")).toHaveLength(1);

    const button = screen.getByRole("button", { name: "Sign in with SSO" });
    expect(button.getAttribute("aria-label")).toBeNull();
  });

  it("the SSO form targets /login/start via GET (AC-17)", async () => {
    mockReadSession.mockResolvedValue(null);

    render(await Page());

    const button = screen.getByRole("button", { name: "Sign in with SSO" });
    const form = button.closest("form");
    expect(form).not.toBeNull();
    expect(form?.getAttribute("action")).toBe("/login/start");
    expect(form?.getAttribute("method")).toBe("get");
  });
});
