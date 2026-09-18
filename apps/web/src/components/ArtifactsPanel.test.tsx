import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";

import { ArtifactsPanel } from "./ArtifactsPanel";
import type { ArtifactItemData, ArtifactsResult } from "@/types/artifacts";

/**
 * SHP-04-TC-09/TC-10 component-level coverage (DESIGN.md § Region ARTIFACTS).
 *
 * D-09 convention (mirrors `ProgramTeamPanel.test.tsx`): native `vitest`
 * mocks only, no MSW. `@/lib/artifactsApi.client` is mocked via its `@/*`
 * alias. No jest-dom matchers are wired in this project -- assertions use
 * `.not.toBeNull()` / `.toBeNull()` / `.toHaveLength()`, never `toBeInTheDocument`.
 */

const fetchProgramArtifacts = vi.fn();

vi.mock("@/lib/artifactsApi.client", () => ({
  fetchProgramArtifacts: (...args: unknown[]) => fetchProgramArtifacts(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function okResult(items: ArtifactItemData[]): ArtifactsResult {
  return { status: "ok", data: { items } };
}

/** SHP-04-TC-09's fixture, verbatim from docs/test-cases/SHP-04.json. */
const FIXTURE_ITEMS: ArtifactItemData[] = [
  { tag: "PRD", name: "PRDs", count: 4, bg: "#EEF2FF", color: "#4338CA" },
  { tag: "US", name: "User stories", count: 45, bg: "#ECFDF5", color: "#047857" },
  { tag: "TC", name: "Test cases", count: 274, bg: "#FFFBEB", color: "#B45309" },
  { tag: "AD", name: "Arch diagrams", count: 0, bg: "#FEF2F2", color: "#B91C1C" },
  { tag: "API", name: "API specs", count: 0, bg: "#F5F3FF", color: "#6D28D9" },
];

describe("ArtifactsPanel", () => {
  it("TC analogue: renders exactly 5 placeholder rows while loading", () => {
    fetchProgramArtifacts.mockReturnValue(new Promise(() => {})); // never resolves

    render(<ArtifactsPanel programId="dashboard" />);

    expect(screen.getAllByTestId("artifacts-row-skeleton")).toHaveLength(5);
  });

  it("SHP-04-TC-09: renders all 5 rows, each pairing tag/name text with its bg/color styling -- never color alone -- and raw-int counts verbatim, including zero rows", async () => {
    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() =>
      expect(screen.queryAllByTestId("artifacts-row-skeleton")).toHaveLength(0),
    );

    for (const item of FIXTURE_ITEMS) {
      const nameEl = screen.getByText(item.name);
      const row = nameEl.closest("div") as HTMLElement;
      const tagEl = within(row).getByText(item.tag);
      const countEl = within(row).getByText(String(item.count));

      // Text label present alongside the styling -- colour is never the
      // sole indicator of artifact type.
      expect(tagEl).not.toBeNull();
      expect(nameEl).not.toBeNull();
      expect(countEl).not.toBeNull();

      expect(tagEl.style.background).toBe(hexToRgb(item.bg));
      expect(tagEl.style.color).toBe(hexToRgb(item.color));

      // The tag chip is decorative -- aria-hidden, redundant with the
      // adjacent full-contrast name label.
      expect(tagEl.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("SHP-04-TC-09: a program with zeros on two of five rows still shows five rows with a literal 0, not a hidden or dimmed row", async () => {
    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());

    const zeroCounts = screen.getAllByText("0");
    expect(zeroCounts).toHaveLength(2);
    expect(screen.getByText("Arch diagrams")).not.toBeNull();
    expect(screen.getByText("API specs")).not.toBeNull();
  });

  it("renders exactly 5 rows in fixture (wire) order, never re-sorted client-side", async () => {
    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());

    const names = screen
      .getAllByText(/PRDs|User stories|Test cases|Arch diagrams|API specs/)
      .map((el) => el.textContent);
    expect(names).toEqual([
      "PRDs",
      "User stories",
      "Test cases",
      "Arch diagrams",
      "API specs",
    ]);
  });

  it("header copy is static literal text with no program-name interpolation", async () => {
    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());

    expect(screen.getByText("Artifacts generated")).not.toBeNull();
    expect(screen.getByText("Outputs produced on this program")).not.toBeNull();
  });

  it("SHP-04-TC-10: renders byte-identically across 3 independent mounts of the standalone component with the same fixture (ARC-01/DEV-01/PMD-01 pages do not exist yet)", async () => {
    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));

    const { unmount: unmount1 } = render(<ArtifactsPanel programId="dashboard" />);
    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());
    const output1 = document.body.innerHTML;
    unmount1();
    cleanup();

    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));
    const { unmount: unmount2 } = render(<ArtifactsPanel programId="dashboard" />);
    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());
    const output2 = document.body.innerHTML;
    unmount2();
    cleanup();

    fetchProgramArtifacts.mockResolvedValue(okResult(FIXTURE_ITEMS));
    const { unmount: unmount3 } = render(<ArtifactsPanel programId="dashboard" />);
    await waitFor(() => expect(screen.getByText("PRDs")).not.toBeNull());
    const output3 = document.body.innerHTML;
    unmount3();

    expect(output1).toBe(output2);
    expect(output2).toBe(output3);
  });

  it("error state renders a notice and no rows", async () => {
    fetchProgramArtifacts.mockResolvedValue({ status: "error" });

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() =>
      expect(screen.getByText("Couldn't load artifacts.")).not.toBeNull(),
    );
    expect(screen.queryByText("PRDs")).toBeNull();
  });

  it("unauthorized result renders the same notice as a generic error", async () => {
    fetchProgramArtifacts.mockResolvedValue({ status: "unauthorized" });

    render(<ArtifactsPanel programId="dashboard" />);

    await waitFor(() =>
      expect(screen.getByText("Couldn't load artifacts.")).not.toBeNull(),
    );
  });
});

/** Browsers normalize inline hex colors to rgb() on the CSSStyleDeclaration. */
function hexToRgb(hex: string): string {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
}
