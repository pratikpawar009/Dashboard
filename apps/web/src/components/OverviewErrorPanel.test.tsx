import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { OverviewErrorPanel } from "./OverviewErrorPanel";

afterEach(() => {
  cleanup();
});

const MESSAGE = "You don't have access to this view.";

// D-07 is deliberately one generic panel, not a per-status family: the same
// message renders for `forbidden`, `unauthorized`, and `error` alike, and the
// optional `status` prop is accepted only for caller context -- it must never
// change the copy. These three cases re-assert the identical string on
// purpose, to prove that uniformity (not to pad coverage): a future change
// that branches copy per status should fail here.
describe("OverviewErrorPanel (OVW-01-AC-3, D-07)", () => {
  it("renders the D-07 fallback message for status=forbidden", () => {
    render(<OverviewErrorPanel status="forbidden" />);

    expect(screen.getByText(MESSAGE).textContent).toBe(MESSAGE);
  });

  it("renders the identical D-07 fallback message for status=unauthorized", () => {
    render(<OverviewErrorPanel status="unauthorized" />);

    expect(screen.getByText(MESSAGE).textContent).toBe(MESSAGE);
  });

  it("renders the identical D-07 fallback message for status=error", () => {
    render(<OverviewErrorPanel status="error" />);

    expect(screen.getByText(MESSAGE).textContent).toBe(MESSAGE);
  });

  it("renders the same message with no status prop at all (props are optional)", () => {
    render(<OverviewErrorPanel />);

    expect(screen.getByText(MESSAGE).textContent).toBe(MESSAGE);
  });
});
