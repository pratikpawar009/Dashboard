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

  // OVW-05 AC-1/AC-2: `cio` is now a fifth valid, renderable persona —
  // `formatPersonaTag("cio")` no longer throws `PersonaTagError`, so this
  // used to assert the neutral badge (D-03) no longer holds for `cio`. This
  // replaces that stale assertion with proof the admission actually took
  // effect: the real tag/subtitle render through the existing program-header
  // path, not the neutral fallback.
  it("renders the normal identity/header path for persona='cio' — no longer the neutral badge (OVW-05 AC-1/AC-2)", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="cio"
        program={PROGRAM}
      />,
    );

    expect(screen.getByText("CIO / CXO").textContent).toBe("CIO / CXO");
    // The subtitle is a bare text sibling of the pill <span> inside
    // PersonaHeader's shared wrapper div (not its own dedicated element), so
    // `.textContent` on the matched node would include the pill's text too —
    // existence (getByText throws if not found) is the correct assertion here.
    expect(
      screen.getByText(
        "Organization-wide AI-in-SDLC adoption, spend & impact",
      ),
    ).not.toBeNull();
    expect(screen.queryByText("Persona unavailable")).toBeNull();
    expect(
      screen.queryByText("Unable to load your dashboard view."),
    ).toBeNull();
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

  // Regression for REVIEW.md F-2 (regression-SHP-01-TC-02): the identity
  // avatar's neutral fallback used to hardcode `#5b6472`/`#e4e7ec` inline in
  // this component, duplicating PersonaHeader.module.css `.pillNeutral`. D-02
  // guarantees the persona tag and the identity avatar can never disagree on a
  // colour; with two independent literals that guarantee held only because the
  // values happened to match. These two cases lock the structural version: the
  // avatar carries NO inline colour on the unresolved path (it takes the shared
  // `--neutral-unresolved-*` token via `.avatarUnknownPersona`), and carries
  // ONLY a persona-derived `background` on the resolved path.
  it("regression-SHP-01-TC-02: unknown persona + known name renders initials with no inline colour, via the shared neutral token", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={{ name: "Devon Rao", jobTitle: "Principal Architect" }}
        persona="persona-resolution-error"
        program={PROGRAM}
      />,
    );

    const avatars = container.getElementsByClassName(shellStyles.avatar);
    expect(avatars).toHaveLength(1);
    const avatar = avatars[0] as HTMLElement;

    // initials still render — the name is known, only the persona is not
    expect(avatar.textContent).toBe("DR");
    // the neutral variant class is applied...
    expect(avatar.className).toContain(shellStyles.avatarUnknownPersona);
    // ...and NO colour is hardcoded inline (that is the defect this locks)
    expect(avatar.style.background).toBe("");
    expect(avatar.style.backgroundColor).toBe("");
    expect(avatar.style.color).toBe("");
  });

  it("regression-SHP-01-TC-02: a valid persona passes ONLY its background inline, never a colour pair", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={{ name: "Devon Rao", jobTitle: "Principal Architect" }}
        persona="architect"
        program={PROGRAM}
      />,
    );

    const avatar = container.getElementsByClassName(
      shellStyles.avatar,
    )[0] as HTMLElement;

    // architect -> #6a4fd0, docs/design/tokens.md § Persona colors; jsdom
    // normalises hex to rgb()
    expect(avatar.style.backgroundColor).toBe("rgb(106, 79, 208)");
    // the neutral variant must NOT be applied on the resolved path
    expect(avatar.className).not.toContain(shellStyles.avatarUnknownPersona);
    // white text is a static CSS rule (D-06), never an inline declaration
    expect(avatar.style.color).toBe("");
  });

  // OVW-01 D-04/T-08: `program` widened to optional for callers with no
  // single-program concept (the org-level `/overview` page). This is the
  // regression guard for the *existing* consumer's contract: a defined
  // `persona` with `program` omitted must still suppress the header region
  // entirely (no `ProgramContext` invocation with an undefined `program`),
  // while every other persona-gated region (identity block) still renders
  // normally, since `isLoading` derives only from `persona`.
  it("OVW-01 D-04: suppresses the header region (PersonaHeader + ProgramContext) when program is omitted, even though persona is resolved", () => {
    const { container } = render(
      <PersonaDashboardShell signedInUser={undefined} persona="architect" />,
    );

    // header region entirely absent — no partial render with a missing program
    expect(container.querySelector("header")).toBeNull();
    expect(
      container.getElementsByClassName(shellStyles.headerRegion),
    ).toHaveLength(0);

    // the persona-gated identity block still renders — `isLoading` only
    // gates on `persona`, unaffected by `program` being omitted
    expect(
      container.getElementsByClassName(shellStyles.identity),
    ).toHaveLength(1);
  });

  // OVW-01 D-04/T-08: existing (program-defined) callers are unaffected —
  // the header region still renders exactly as before when `program` is
  // provided, proving the widened optional type is backwards-compatible.
  it("OVW-01 D-04: still renders the header region (PersonaHeader + ProgramContext) when program is provided, unchanged from before the widening", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="architect"
        program={PROGRAM}
      />,
    );

    expect(container.querySelector("header")).not.toBeNull();
    expect(screen.getByText(PROGRAM.name).textContent).toBe(PROGRAM.name);
    expect(screen.getByText(PROGRAM.description).textContent).toBe(
      PROGRAM.description,
    );
  });

  // OVW-01 D-04/T-08: new `children` slot renders after the brand bar,
  // regardless of `persona`/`program` — `AdoptionOverview` (a later task)
  // relies on this to host its own content beneath the shared chrome.
  it("OVW-01 D-04: renders children after the brand bar", () => {
    render(
      <PersonaDashboardShell signedInUser={undefined} persona={undefined}>
        <div data-testid="overview-content">Org summary content</div>
      </PersonaDashboardShell>,
    );

    expect(screen.getByTestId("overview-content").textContent).toBe(
      "Org summary content",
    );
  });
});

// OVW-05 AC-8/AC-9/AC-10 — the org-header variant, selected purely by prop
// presence (`pageTitle !== undefined && program === undefined`), mutually
// exclusive with the shipped program variant.
describe("PersonaDashboardShell — org-header variant (OVW-05 AC-8/AC-9/AC-10)", () => {
  it("renders the page title, persona pill, and subtitle when pageTitle is set and program is omitted (AC-8/AC-9)", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="cio"
        pageTitle="Adoption Overview"
      />,
    );

    expect(screen.getByText("Adoption Overview").textContent).toBe(
      "Adoption Overview",
    );
    expect(screen.getByText("CIO / CXO").textContent).toBe("CIO / CXO");
    expect(
      screen.getByText(
        "Organization-wide AI-in-SDLC adoption, spend & impact",
      ).textContent,
    ).toBe("Organization-wide AI-in-SDLC adoption, spend & impact");
  });

  it("selects the org-header variant, not the program variant, when program is omitted (mutual exclusivity)", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="architect"
        pageTitle="Adoption Overview"
      />,
    );

    expect(container.querySelectorAll("header")).toHaveLength(1);
    expect(
      container.getElementsByClassName(shellStyles.pageTitle),
    ).toHaveLength(1);
    // never the program variant's ProgramContext content
    expect(screen.queryByText(PROGRAM.name)).toBeNull();
  });

  it("selects the program variant, not the org-header variant, when program is defined even alongside pageTitle (mutual exclusivity)", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="architect"
        program={PROGRAM}
        pageTitle="Adoption Overview"
      />,
    );

    expect(container.querySelectorAll("header")).toHaveLength(1);
    expect(
      container.getElementsByClassName(shellStyles.pageTitle),
    ).toHaveLength(0);
    expect(screen.getByText(PROGRAM.name).textContent).toBe(PROGRAM.name);
  });

  it("suppresses the org header entirely while persona is unresolved, no skeleton (AC-10)", () => {
    const { container } = render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona={undefined}
        pageTitle="Adoption Overview"
      />,
    );

    expect(container.querySelector("header")).toBeNull();
    expect(screen.queryByText("Adoption Overview")).toBeNull();
    expect(
      container.getElementsByClassName(shellStyles.identity),
    ).toHaveLength(0);
    expect(findSkeletonMarkup(container)).toHaveLength(0);

    // brand bar's static left half still renders
    expect(screen.getByText("AgentRise Harness").textContent).toBe(
      "AgentRise Harness",
    );
    expect(screen.getByText("AI SDLC Governance").textContent).toBe(
      "AI SDLC Governance",
    );
  });

  it("degrades the pill to the neutral badge when persona is unresolvable, while the page title still renders", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="persona-resolution-error"
        pageTitle="Adoption Overview"
      />,
    );

    expect(screen.getByText("Adoption Overview").textContent).toBe(
      "Adoption Overview",
    );

    const badge = screen.getByText("Persona unavailable");
    expect(badge.textContent).toBe("Persona unavailable");

    const announcement = screen.getByText(
      "Unable to load your dashboard view.",
    );
    expect(announcement.getAttribute("aria-live")).toBe("assertive");
  });
});

// OVW-05 AC-12/AC-13/AC-14/AC-15 — the sign-out control. AC-12's own text
// flags this as shipping untested today: the control is a SIBLING of the
// `signedInUser` ternary, gated only by `!isLoading`, so it must render in
// BOTH the populated and the D-05 neutral-fallback branch. A regression that
// nests it inside either branch would pass one of the next two cases and
// fail the other — both are asserted explicitly, not just one.
describe("PersonaDashboardShell — sign-out control (OVW-05 AC-12/AC-13/AC-14/AC-15)", () => {
  it("renders with signedInUser defined, with an accessible name matching its visible text 'Sign out'", () => {
    render(
      <PersonaDashboardShell
        signedInUser={{ name: "Devon Rao", jobTitle: "Principal Architect" }}
        persona="architect"
        program={PROGRAM}
      />,
    );

    const signOut = screen.getByRole("button", { name: "Sign out" });
    expect(signOut.textContent).toBe("Sign out");
  });

  it("renders with signedInUser undefined (D-05 neutral-fallback branch) — the AC-12 branch-placement guard", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona="architect"
        program={PROGRAM}
      />,
    );

    const signOut = screen.getByRole("button", { name: "Sign out" });
    expect(signOut.textContent).toBe("Sign out");
  });

  it("does not render while persona is unresolved (AC-14)", () => {
    render(
      <PersonaDashboardShell
        signedInUser={undefined}
        persona={undefined}
        program={PROGRAM}
      />,
    );

    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("targets the existing GET /logout Route Handler via a plain form submit — no new logout logic (AC-13)", () => {
    render(
      <PersonaDashboardShell
        signedInUser={{ name: "Devon Rao", jobTitle: "Principal Architect" }}
        persona="architect"
        program={PROGRAM}
      />,
    );

    const signOut = screen.getByRole("button", { name: "Sign out" });
    const form = signOut.closest("form");
    expect(form).not.toBeNull();
    expect(form?.getAttribute("action")).toBe("/logout");
    expect(form?.getAttribute("method")).toBe("get");
  });
});
