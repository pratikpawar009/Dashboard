import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { ProgramDetailView } from "./ProgramDetailView";
import { ADOPTION_OVERVIEW_ROUTE } from "@/lib/routes";
import type {
  ProgramDetailHeaderData,
  ProgramDetailResult,
  ProgramSwitcherEntry,
} from "@/types/programDetail";

/**
 * PGD-01-TC-03, implemented against `ProgramDetailView` directly rather
 * than T-13's thin Server Component page wrapper (equivalent behavioural
 * coverage without fighting Next.js server-component-in-vitest limits).
 *
 * D-09: native `vitest` mocks only -- no MSW. `@/lib/programDetailApi.client`
 * is mocked via its `@/*` alias (this file's own real import path, per
 * `.claude/skills/typescript-patterns`) -- AUTH-05/D-08 retargeted this mock
 * from the server module `@/lib/programDetailApi` to the client module,
 * since `ProgramDetailView` now calls the client-side proxy fetcher, never
 * FastAPI directly. `next/navigation`'s `useRouter` is mocked directly.
 */

const mockReplace = vi.fn();
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
}));

const fetchProgramDetail = vi.fn();
const fetchPrograms = vi.fn();

vi.mock("@/lib/programDetailApi.client", () => ({
  fetchProgramDetail: (...args: unknown[]) => fetchProgramDetail(...args),
  fetchPrograms: (...args: unknown[]) => fetchPrograms(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const HEADER_A: ProgramDetailHeaderData = {
  icon: "\u{1F3D7}",
  name: "Platform Modernization",
  type: "Migration",
  description: "Core platform upgrade",
};

const HEADER_B: ProgramDetailHeaderData = {
  icon: "\u{1F680}",
  name: "Growth Initiative",
  type: "Greenfield feature development",
  description: "New growth surface",
};

function okResult(
  header: ProgramDetailHeaderData,
  valuePrefix: string,
): ProgramDetailResult {
  return {
    status: "ok",
    data: {
      header,
      summary: Array.from({ length: 7 }).map((_, index) => ({
        glyph: "⬡",
        value: `${valuePrefix}-${index}`,
        label: `Label ${index}`,
      })),
    },
  };
}

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

describe("ProgramDetailView (PGD-01-TC-03)", () => {
  beforeEach(() => {
    fetchPrograms.mockResolvedValue(SWITCHER_OPTIONS);
  });

  it("selecting a program calls fetchProgramDetail with the new id and {switchedFrom: <previous id>}", async () => {
    fetchProgramDetail.mockResolvedValue(okResult(HEADER_B, "B"));

    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={okResult(HEADER_A, "A")}
      />,
    );
    await waitFor(() => expect(fetchPrograms).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: /Platform Modernization/ }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: /Growth Initiative/ }),
    );

    await waitFor(() =>
      expect(fetchProgramDetail).toHaveBeenCalledWith("prog-099", {
        switchedFrom: "prog-042",
      }),
    );
    // AUTH-05 AC-10/AC-11 (D-08): the client module has no token to attach --
    // confirm the call carries {switchedFrom} only, with no accessToken key,
    // rather than relying solely on toHaveBeenCalledWith's shape match.
    const [, callOpts] = fetchProgramDetail.mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(callOpts).not.toHaveProperty("accessToken");
    expect(Object.keys(callOpts)).toEqual(["switchedFrom"]);
  });

  it("updates the URL via router.replace and never hard-navigates", async () => {
    fetchProgramDetail.mockResolvedValue(okResult(HEADER_B, "B"));
    const originalHref = window.location.href;

    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={okResult(HEADER_A, "A")}
      />,
    );
    await waitFor(() => expect(fetchPrograms).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: /Platform Modernization/ }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: /Growth Initiative/ }),
    );

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/programs/prog-099"),
    );
    expect(mockPush).not.toHaveBeenCalled();
    // No hard navigation occurred -- jsdom's location is untouched.
    expect(window.location.href).toBe(originalHref);
  });

  it("re-renders the header and cards in place after the switch resolves", async () => {
    fetchProgramDetail.mockResolvedValue(okResult(HEADER_B, "B"));

    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={okResult(HEADER_A, "A")}
      />,
    );
    await waitFor(() => expect(fetchPrograms).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("program-detail-header-name").textContent).toBe(
      HEADER_A.name,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Platform Modernization/ }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: /Growth Initiative/ }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("program-detail-header-name").textContent).toBe(
        HEADER_B.name,
      ),
    );
    const cards = screen.getAllByTestId("program-summary-card");
    expect(cards[0].textContent).toContain("B-0");
  });

  it("the back-link targets the imported ADOPTION_OVERVIEW_ROUTE and is nested inside ProgramDetailHeader's sticky wrapper (AF-05)", () => {
    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={okResult(HEADER_A, "A")}
      />,
    );

    const link = screen.getByRole("link", {
      name: /Back to program board/,
    });
    expect(link.getAttribute("href")).toBe(ADOPTION_OVERVIEW_ROUTE);

    // AF-05: BackToProgramBoard must render inside ProgramDetailHeader's own
    // sticky wrapper (DESIGN.md Region 1, mockup L389 first child), not as a
    // ProgramDetailView-level sibling above it — assert the link shares an
    // ancestor with the header's identity element rather than only checking
    // the link exists somewhere in the tree.
    const headerName = screen.getByTestId("program-detail-header-name");
    expect(link.parentElement?.contains(headerName)).toBe(true);
  });

  it("an initialResult of {status:'not_found'} renders the error state, keeps the back-link (D-03), and never calls fetchPrograms", () => {
    const notFound: ProgramDetailResult = { status: "not_found" };

    render(
      <ProgramDetailView
        initialProgramId="prog-404"
        initialResult={notFound}
      />,
    );

    expect(
      screen.getByTestId("program-detail-header-error-text").textContent,
    ).toBe("Program not found");
    expect(screen.queryAllByTestId("program-summary-card")).toHaveLength(0);
    expect(screen.getByText("This program could not be found.")).not.toBeNull();
    expect(fetchPrograms).not.toHaveBeenCalled();

    // D-03: "header chrome + back-link" is retained even when the rest of
    // the header collapses to the fallback line.
    const link = screen.getByRole("link", { name: /Back to program board/ });
    expect(link.getAttribute("href")).toBe(ADOPTION_OVERVIEW_ROUTE);
  });

  it("the switcher trigger exposes aria-haspopup/aria-expanded and responds to Enter and Space", async () => {
    render(
      <ProgramDetailView
        initialProgramId="prog-042"
        initialResult={okResult(HEADER_A, "A")}
      />,
    );
    await waitFor(() => expect(fetchPrograms).toHaveBeenCalledTimes(1));

    const trigger = screen.getByRole("button", {
      name: /Platform Modernization/,
    });
    expect(trigger.getAttribute("aria-haspopup")).toBe("true");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    // jsdom does not turn a focused <button>'s Enter/Space keydown into a
    // click by itself (no @testing-library/user-event dependency, per D-09)
    // -- exercise the real key sequence, then the click a real browser
    // fires as that key's default action on a native button (same idiom as
    // ProgramSwitcher.test.tsx).
    fireEvent.keyDown(trigger, { key: "Enter", code: "Enter" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu")).not.toBeNull();

    fireEvent.keyDown(trigger, { key: " ", code: "Space" });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("a mocked {status:'unauthorized'} switch result sets window.location.href to /login (AC-8/FR-5 client-side half) without a client-side route transition", async () => {
    fetchProgramDetail.mockResolvedValue({ status: "unauthorized" });

    // jsdom's window.location is not reassignable by default -- redefine it
    // for the duration of this test only, and restore the original
    // afterwards so the "never hard-navigates" test above (which reads
    // window.location.href) is unaffected by this stubbing.
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      value: { href: "" },
      writable: true,
      configurable: true,
    });

    try {
      render(
        <ProgramDetailView
          initialProgramId="prog-042"
          initialResult={okResult(HEADER_A, "A")}
        />,
      );
      await waitFor(() => expect(fetchPrograms).toHaveBeenCalledTimes(1));

      fireEvent.click(
        screen.getByRole("button", { name: /Platform Modernization/ }),
      );
      fireEvent.click(
        screen.getByRole("menuitem", { name: /Growth Initiative/ }),
      );

      await waitFor(() => expect(window.location.href).toBe("/login"));
      expect(mockReplace).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, "location", {
        value: originalLocation,
        writable: true,
        configurable: true,
      });
    }
  });
});
