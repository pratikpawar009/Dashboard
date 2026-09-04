import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ProgramSwitcher, type ProgramSwitcherProps } from "./ProgramSwitcher";
import type { ProgramSwitcherEntry } from "@/types/programDetail";

afterEach(() => {
  cleanup();
});

const OPTIONS: ProgramSwitcherEntry[] = [
  {
    program_id: "prog-1",
    label: "Platform Modernization",
    href: "/programs/prog-1",
    dotStyle: "background-color: #0f1a2e;",
  },
  {
    program_id: "prog-2",
    label: "Growth Initiative",
    href: "/programs/prog-2",
    dotStyle: "background-color: #1f8a5b;",
  },
];

function baseProps(overrides: Partial<ProgramSwitcherProps> = {}): ProgramSwitcherProps {
  return {
    options: OPTIONS,
    currentProgramId: "prog-1",
    isOpen: false,
    onToggle: vi.fn(),
    onSelect: vi.fn(),
    isLoadingOptions: false,
    ...overrides,
  };
}

describe("ProgramSwitcher (PGD-01-AC-5)", () => {
  it("exposes aria-haspopup and aria-expanded reflecting the isOpen prop", () => {
    const { rerender } = render(<ProgramSwitcher {...baseProps({ isOpen: false })} />);
    const trigger = screen.getByRole("button", {
      name: /Platform Modernization/,
    });
    expect(trigger.getAttribute("aria-haspopup")).toBe("true");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    rerender(<ProgramSwitcher {...baseProps({ isOpen: true })} />);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("is a real <button> whose click handler is onToggle, so native Enter/Space activation reaches it", () => {
    const onToggle = vi.fn();
    render(<ProgramSwitcher {...baseProps({ onToggle })} />);
    const trigger = screen.getByRole("button", {
      name: /Platform Modernization/,
    });

    expect(trigger.tagName).toBe("BUTTON");
    expect((trigger as HTMLButtonElement).type).toBe("button");

    // jsdom does not implement the browser's default action that turns a
    // focused <button>'s Enter/Space keydown into a click event (no
    // @testing-library/user-event dependency, per D-09) -- exercise the real
    // key sequence, then the click a real browser fires as Enter/Space's
    // default action on a native button, and assert it reaches onToggle.
    fireEvent.keyDown(trigger, { key: "Enter", code: "Enter" });
    fireEvent.click(trigger);
    expect(onToggle).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(trigger, { key: " ", code: "Space" });
    fireEvent.keyUp(trigger, { key: " ", code: "Space" });
    fireEvent.click(trigger);
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("is absent from the DOM when closed and renders one menuitem per option when open", () => {
    const { rerender } = render(<ProgramSwitcher {...baseProps({ isOpen: false })} />);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.queryAllByRole("menuitem")).toHaveLength(0);

    rerender(<ProgramSwitcher {...baseProps({ isOpen: true })} />);
    expect(screen.getByRole("menu")).not.toBeNull();
    const rows = screen.getAllByRole("menuitem");
    expect(rows).toHaveLength(OPTIONS.length);
    expect(rows.map((row) => row.tagName)).toEqual(["BUTTON", "BUTTON"]);
  });

  it("shows the current-row check only on the row matching currentProgramId", () => {
    render(<ProgramSwitcher {...baseProps({ isOpen: true, currentProgramId: "prog-2" })} />);

    const rows = screen.getAllByRole("menuitem");
    const currentRow = rows.find((row) => row.textContent?.includes("Growth Initiative"));
    const otherRow = rows.find((row) => row.textContent?.includes("Platform Modernization"));

    expect(currentRow?.textContent).toContain("✓");
    expect(otherRow?.textContent).not.toContain("✓");
  });

  it("selecting a row calls onSelect with that row's program_id, never navigating", () => {
    const onSelect = vi.fn();
    render(<ProgramSwitcher {...baseProps({ isOpen: true, onSelect })} />);

    const rows = screen.getAllByRole("menuitem");
    const targetRow = rows.find((row) => row.textContent?.includes("Growth Initiative"));
    expect(targetRow?.tagName).toBe("BUTTON");
    fireEvent.click(targetRow!);

    expect(onSelect).toHaveBeenCalledWith("prog-2");
  });

  it("renders a disabled trigger and no menu when options is empty", () => {
    render(
      <ProgramSwitcher {...baseProps({ options: [], isOpen: true })} />,
    );

    const trigger = screen.getByRole("button");
    expect((trigger as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("renders a disabled trigger while isLoadingOptions is true", () => {
    render(
      <ProgramSwitcher {...baseProps({ isLoadingOptions: true, isOpen: true })} />,
    );

    const trigger = screen.getByRole("button");
    expect((trigger as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
