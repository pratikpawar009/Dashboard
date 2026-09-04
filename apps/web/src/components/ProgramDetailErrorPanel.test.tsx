import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ProgramDetailErrorPanel } from "./ProgramDetailErrorPanel";

afterEach(() => {
  cleanup();
});

describe("ProgramDetailErrorPanel (PGD-01-AC-7, D-03)", () => {
  it("renders the D-03 fallback message", () => {
    render(<ProgramDetailErrorPanel />);

    expect(
      screen.getByText("This program could not be found.").textContent,
    ).toBe("This program could not be found.");
  });
});
