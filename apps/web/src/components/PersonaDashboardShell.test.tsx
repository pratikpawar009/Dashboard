import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { PersonaDashboardShell } from "./PersonaDashboardShell";
import shellStyles from "./PersonaDashboardShell.module.css";
import type { ProgramContextData } from "@/types/persona";

afterEach(() => {
  cleanup();
});

/**
 * SHP-01-TC-02. Vocabulary translation from the test-case JSON, which
 * predates the finalized prop contract (D-01/D-03,
 * docs/requirements/api.md#persona-shell): the shell has no `session` prop
 * and no resolver dependency of its own.
 * - "session + persona unresolved" -> `persona={undefined}`.
 * - "the resolver raised `PersonaNotFoundError`" -> the composing page
 *   catches that and passes a sentinel string in `persona`.
 * - "signedInUser undefined" -> `signedInUser={undefined}`.
 */

// A fully-resolved `program` prop, reused wherever `program` itself isn't
// the thing under test.
const PROGRAM: ProgramContextData = {
  icon: "🏗️",
  name: "Platform Modernization",
  type: "Migration",
  description: "Core platform upgrade",
};

// Positively asserts no placeholder/skeleton markup exists, rather than
// only asserting the absence of real content.
function findSkeletonMarkup(container: HTMLElement): Element[] {
  return Array.from(container.querySelectorAll("*")).filter(
    (el) =>
      /skeleton|placeholder/i.test(el.className.toString()) ||
      /skeleton|placeholder/i.test(el.getAttribute("data-testid") ?? ""),
  );
}

// D-03 — a resolver-error sentinel and `cio` share one neutral-badge path,
// not two; both scenarios assert this identical shape.
function expectNeutralErrorBadge() {
  const badge = screen.getByText("Persona unavailable");
  expect(badge.textContent).toBe("Persona unavailable");
  expect(screen.queryByText(/overview/i)).toBeNull();

  const announcement = screen.getByText(
    "Unable to load your dashboard view.",
  );
  expect(announcement.textContent).toBe(
    "Unable to load your dashboard view.",
  );
  expect(announcement.getAttribute("aria-live")).toBe("assertive");
}

describe("PersonaDashboardShell (SHP-01-TC-02)", () => {
  it("suppresses every persona-gated region while persona is unresolved, with no skeleton markup", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona={undefined}
        program={PROGRAM}
      />,
    );

    expect(screen.getByText("AgentRise Harness").textContent).toBe(
      "AgentRise Harness",
    );
    expect(screen.getByText("AI SDLC Governance").textContent).toBe(
      "AI SDLC Governance",
    );

    // identity block absent
    expect(container.querySelector('[aria-hidden="true"]')).toBeNull();
    expect(
      container.getElementsByClassName(shellStyles.identity),
    ).toHaveLength(0);

    // persona tag / subtitle / program context all live inside the header
    // region, which the loading gate omits entirely — no partial render.
    expect(container.querySelector("header")).toBeNull();
    expect(screen.queryByText(/overview/i)).toBeNull();
    expect(screen.queryByText(PROGRAM.name)).toBeNull();
    expect(screen.queryByText(PROGRAM.description)).toBeNull();
    expect(screen.queryByText(PROGRAM.icon)).toBeNull();
    expect(screen.queryByText(PROGRAM.type)).toBeNull();

    expect(findSkeletonMarkup(container)).toHaveLength(0);
  });

  it("shows the neutral badge + aria-live announcement when persona is a resolver-error sentinel", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="persona-resolution-error"
        program={PROGRAM}
      />,
    );

    expectNeutralErrorBadge();
  });

  it("shows the identical neutral badge + aria-live announcement for persona='cio' (D-03 — one path, not two)", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="cio"
        program={PROGRAM}
      />,
    );

    expectNeutralErrorBadge();
  });

  it("falls back to the neutral identity circle when signedInUser is undefined, with no name/jobTitle text", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="architect"
        program={PROGRAM}
      />,
    );

    const neutralCircle = container.querySelector('[aria-hidden="true"]');
    expect(neutralCircle).not.toBeNull();
    expect(neutralCircle?.textContent).toBe("");

    expect(container.getElementsByClassName(shellStyles.name)).toHaveLength(
      0,
    );
    expect(
      container.getElementsByClassName(shellStyles.jobTitle),
    ).toHaveLength(0);
  });
});
