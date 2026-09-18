import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { SessionsTable } from "./SessionsTable";
import type {
  PersonalSessionEntryData,
  PersonalSessionsData,
  PersonalSessionsResult,
} from "@/types/personalSessions";

/**
 * SHP-03-TC-12/TC-13 component-level coverage (PLAN.md § 7): table semantics,
 * aria-current on active page, accessible prev/next names, empty state, 403
 * state.
 *
 * D-09 convention (mirrors `ArtifactsPanel.test.tsx`): native `vitest` mocks
 * only, no MSW. `@/lib/personalSessionsApi.client` is mocked via its `@/*`
 * alias. No jest-dom matchers are wired in this project -- assertions use
 * `.not.toBeNull()` / `.toBeNull()` / `.toHaveLength()`, never `toBeInTheDocument`.
 */

const fetchPersonalSessions = vi.fn();

vi.mock("@/lib/personalSessionsApi.client", () => ({
  fetchPersonalSessions: (...args: unknown[]) => fetchPersonalSessions(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function okResult(data: PersonalSessionsData): PersonalSessionsResult {
  return { status: "ok", data };
}

const FIXTURE_ITEMS: PersonalSessionEntryData[] = [
  { title: "Refactor auth middleware", meta: "S-1088 · Jul 5, 2026", duration: "2h 07m", tokens: "840K" },
  { title: "Fix flaky ingest test", meta: "S-1091 · Jul 4, 2026", duration: "48m", tokens: "212K" },
];

function pageData(overrides: Partial<PersonalSessionsData> = {}): PersonalSessionsData {
  return {
    items: FIXTURE_ITEMS,
    page: 1,
    page_size: 20,
    total: 2,
    ...overrides,
  };
}

describe("SessionsTable", () => {
  it("renders 20 skeleton rows while loading", () => {
    fetchPersonalSessions.mockReturnValue(new Promise(() => {})); // never resolves

    render(<SessionsTable userId="u-1" />);

    expect(screen.getAllByTestId("sessions-row-skeleton")).toHaveLength(20);
  });

  it("renders a subtitle only when programName is supplied", async () => {
    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));

    const { unmount } = render(<SessionsTable userId="u-1" programName="Dashboard" />);
    await waitFor(() =>
      expect(screen.queryAllByTestId("sessions-row-skeleton")).toHaveLength(0),
    );
    expect(screen.getByText("Your recent sessions on Dashboard")).not.toBeNull();
    unmount();
    cleanup();

    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));
    render(<SessionsTable userId="u-1" />);
    await waitFor(() =>
      expect(screen.queryAllByTestId("sessions-row-skeleton")).toHaveLength(0),
    );
    expect(screen.queryByText(/Your recent sessions on/)).toBeNull();
  });

  it("SHP-03-TC-12: table semantics -- real <table> with column headers exposing accessible names", async () => {
    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());

    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Session", "Duration", "Tokens"]);
  });

  it("SHP-03-TC-12: values render verbatim -- duration/tokens/meta are not reformatted", async () => {
    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());

    expect(screen.getByText("2h 07m")).not.toBeNull();
    expect(screen.getByText("840K")).not.toBeNull();
    expect(screen.getByText("S-1088 · Jul 5, 2026")).not.toBeNull();
    expect(screen.getByText("48m")).not.toBeNull();
    expect(screen.getByText("212K")).not.toBeNull();
    expect(screen.getByText("S-1091 · Jul 4, 2026")).not.toBeNull();
  });

  it("SHP-03-TC-12: aria-current='page' is on the active page button and moves when another page is selected", async () => {
    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ page: 1, page_size: 20, total: 40 })),
    );

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());

    const page1Button = screen.getByRole("button", { name: "Page 1" });
    const page2Button = screen.getByRole("button", { name: "Page 2" });

    expect(page1Button.getAttribute("aria-current")).toBe("page");
    expect(page2Button.getAttribute("aria-current")).toBeNull();

    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ page: 2, page_size: 20, total: 40 })),
    );

    fireEvent.click(page2Button);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Page 2" }).getAttribute("aria-current")).toBe(
        "page",
      ),
    );
    expect(screen.getByRole("button", { name: "Page 1" }).getAttribute("aria-current")).toBeNull();
  });

  it("SHP-03-TC-12: prev/next carry accessible names distinct from their glyphs", async () => {
    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ page: 2, page_size: 20, total: 40 })),
    );

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());

    const prevButton = screen.getByRole("button", { name: "Previous page" });
    const nextButton = screen.getByRole("button", { name: "Next page" });

    expect(prevButton).not.toBeNull();
    expect(nextButton).not.toBeNull();
  });

  it("pagination interaction: clicking a page number re-fetches with the right page argument", async () => {
    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ page: 1, page_size: 20, total: 60 })),
    );

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());
    expect(fetchPersonalSessions).toHaveBeenLastCalledWith("u-1", 1, 20);

    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ page: 3, page_size: 20, total: 60 })),
    );

    fireEvent.click(screen.getByRole("button", { name: "Page 3" }));

    await waitFor(() =>
      expect(fetchPersonalSessions).toHaveBeenLastCalledWith("u-1", 3, 20),
    );
  });

  it("SHP-03-TC-13: empty state renders its copy and suppresses pagination", async () => {
    fetchPersonalSessions.mockResolvedValue(
      okResult(pageData({ items: [], page: 1, page_size: 20, total: 0 })),
    );

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByText("No sessions yet.")).not.toBeNull());

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Previous page" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Page \d+$/ })).toBeNull();
  });

  it("SHP-03-TC-13: 403/denied state renders its alert and does not render the table", async () => {
    fetchPersonalSessions.mockResolvedValue({ status: "denied" });

    render(<SessionsTable userId="u-1" />);

    await waitFor(() =>
      expect(screen.getByText("You don't have access to these sessions.")).not.toBeNull(),
    );

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("You don't have access to these sessions.");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("error state renders its own distinct copy", async () => {
    fetchPersonalSessions.mockResolvedValue({ status: "error" });

    render(<SessionsTable userId="u-1" />);

    await waitFor(() => expect(screen.getByText("Couldn't load sessions.")).not.toBeNull());

    expect(screen.queryByText("You don't have access to these sessions.")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders byte-identically across 3 independent mounts of the standalone component with the same fixture (ARC-01/DEV-01/PMD-01 pages do not exist yet)", async () => {
    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));
    const { unmount: unmount1 } = render(<SessionsTable userId="u-1" />);
    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());
    const output1 = document.body.innerHTML;
    unmount1();
    cleanup();

    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));
    const { unmount: unmount2 } = render(<SessionsTable userId="u-1" />);
    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());
    const output2 = document.body.innerHTML;
    unmount2();
    cleanup();

    fetchPersonalSessions.mockResolvedValue(okResult(pageData()));
    const { unmount: unmount3 } = render(<SessionsTable userId="u-1" />);
    await waitFor(() => expect(screen.getByRole("table")).not.toBeNull());
    const output3 = document.body.innerHTML;
    unmount3();

    expect(output1).toBe(output2);
    expect(output2).toBe(output3);
  });
});
