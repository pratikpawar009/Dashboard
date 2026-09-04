import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ProgramDetailHeader } from "./ProgramDetailHeader";
import type { ProgramDetailHeaderData } from "@/types/programDetail";
import type { ProgramSwitcherProps } from "./ProgramSwitcher";

afterEach(() => {
  cleanup();
});

const HEADER: ProgramDetailHeaderData = {
  icon: "🏗️",
  name: "Platform Modernization",
  type: "Migration",
  description: "Core platform upgrade",
};

function baseSwitcher(
  overrides: Partial<ProgramSwitcherProps> = {},
): ProgramSwitcherProps {
  return {
    options: [],
    currentProgramId: "prog-1",
    isOpen: false,
    onToggle: vi.fn(),
    onSelect: vi.fn(),
    isLoadingOptions: false,
    ...overrides,
  };
}

describe("ProgramDetailHeader (PGD-01-AC-2)", () => {
  it("populated: renders avatar/name/type-chip/description and the switcher, never the persona chip", () => {
    const { container } = render(
      <ProgramDetailHeader
        state="populated"
        header={HEADER}
        switcher={baseSwitcher()}
      />,
    );

    expect(screen.getByTestId("program-detail-header-avatar").textContent).toBe(
      HEADER.icon,
    );
    expect(screen.getByTestId("program-detail-header-name").textContent).toBe(
      HEADER.name,
    );
    expect(
      screen.getByTestId("program-detail-header-type-chip").textContent,
    ).toBe(HEADER.type);
    expect(
      screen.getByTestId("program-detail-header-description").textContent,
    ).toBe(HEADER.description);

    // Region 3 delegated to ProgramSwitcher — rendered as a child.
    expect(screen.getByText("Switch program")).not.toBeNull();

    // D-01: the mockup's static persona chip must never render from this shell.
    expect(screen.queryByText("CIO / CXO")).toBeNull();

    // AF-05 (DESIGN.md Region 1, mockup L389): BackToProgramBoard must be
    // the first child inside this component's own sticky wrapper, not a
    // sibling rendered elsewhere — assert the DOM position directly rather
    // than only its presence.
    const link = screen.getByRole("link", { name: /Back to program board/ });
    expect(container.firstElementChild?.firstElementChild).toBe(link);
  });

  it("loading: keeps the populated geometry but suppresses all text content", () => {
    const { container } = render(
      <ProgramDetailHeader state="loading" switcher={baseSwitcher()} />,
    );

    expect(screen.getByTestId("program-detail-header-avatar").textContent).toBe(
      "",
    );
    expect(screen.getByTestId("program-detail-header-name").textContent).toBe(
      "",
    );
    expect(
      screen.getByTestId("program-detail-header-type-chip").textContent,
    ).toBe("");
    expect(
      screen.getByTestId("program-detail-header-description").textContent,
    ).toBe("");

    // The switcher control still mounts at loading geometry.
    expect(screen.getByText("Switch program")).not.toBeNull();

    expect(screen.queryByText(HEADER.name)).toBeNull();
    expect(screen.queryByText("CIO / CXO")).toBeNull();

    // AF-05: still nested as the sticky wrapper's first child at loading state.
    const link = screen.getByRole("link", { name: /Back to program board/ });
    expect(container.firstElementChild?.firstElementChild).toBe(link);
  });

  it("error: renders the fallback text plus the back-link (D-03) — no avatar/description/switcher", () => {
    const { container } = render(
      <ProgramDetailHeader state="error" switcher={baseSwitcher()} />,
    );

    expect(
      screen.getByTestId("program-detail-header-error-text").textContent,
    ).toBe("Program not found");

    expect(screen.queryByTestId("program-detail-header-avatar")).toBeNull();
    expect(
      screen.queryByTestId("program-detail-header-description"),
    ).toBeNull();
    expect(screen.queryByText("Switch program")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("CIO / CXO")).toBeNull();

    // D-03: "header chrome + back-link" is retained in the error state.
    // AF-05: replaces the old (incorrect) absence assumption with a positive
    // assertion that the link renders here, nested as the sticky wrapper's
    // first child, ahead of the fallback text.
    const link = screen.getByRole("link", { name: /Back to program board/ });
    expect(container.firstElementChild?.firstElementChild).toBe(link);
  });
});
