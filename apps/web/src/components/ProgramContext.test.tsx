import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ProgramContext } from "./ProgramContext";
import type { ProgramContextData } from "@/types/persona";

afterEach(() => {
  cleanup();
});

// docs/design/tokens.md § Program type colors — the cross-check source for
// this test. Deliberately NOT imported from @/lib/programStyle: asserting
// getProgramStyle()'s output against itself would prove nothing (SHP-01-TC-03).
const TOKENS_MD_PROGRAM_TYPE_COLORS: Record<
  string,
  { color: string; background: string }
> = {
  Migration: { color: "#2a6fdb", background: "#eaf1fc" },
  Maintenance: { color: "#c08a1e", background: "#fdf3e0" },
};

// jsdom normalizes hex colors applied via inline style to rgb(...) form, so
// comparisons must go through the same conversion rather than the raw hex.
function hexToRgb(hex: string): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
}

describe("ProgramContext (SHP-01-TC-03)", () => {
  it("renders icon/name/description/type verbatim and applies the tokens.md-sourced Migration color pair", () => {
    const program: ProgramContextData = {
      icon: "🏗️",
      name: "Platform Modernization",
      type: "Migration",
      description: "Core platform upgrade",
    };

    render(<ProgramContext program={program} />);

    const avatar = screen.getByText(program.icon);
    const typeChip = screen.getByText(program.type);

    expect(screen.getByText(program.name).textContent).toBe(program.name);
    expect(screen.getByText(program.description).textContent).toBe(
      program.description,
    );
    expect(typeChip.textContent).toBe(program.type);

    const migration = TOKENS_MD_PROGRAM_TYPE_COLORS.Migration;
    expect(avatar.style.color).toBe(hexToRgb(migration.color));
    expect(avatar.style.backgroundColor).toBe(hexToRgb(migration.background));
    expect(typeChip.style.color).toBe(hexToRgb(migration.color));
    expect(typeChip.style.backgroundColor).toBe(
      hexToRgb(migration.background),
    );
  });

  it("ignores a caller-supplied avatarStyle field and still applies the tokens.md-sourced Maintenance color pair", () => {
    // avatarStyle is deliberately not on ProgramContextData — the component
    // destructures only {icon, name, type, description} off the prop, so an
    // extraneous style field must never be read (FR-4/C-5).
    const programWithInjectedStyle: ProgramContextData & {
      avatarStyle: string;
    } = {
      icon: "🚀",
      name: "Growth Initiative",
      type: "Maintenance",
      description: "New market launch",
      avatarStyle: "background:#ff0000",
    };

    const { container } = render(
      <ProgramContext program={programWithInjectedStyle} />,
    );

    const avatar = screen.getByText(programWithInjectedStyle.icon);
    const typeChip = screen.getByText(programWithInjectedStyle.type);

    expect(screen.getByText(programWithInjectedStyle.name).textContent).toBe(
      programWithInjectedStyle.name,
    );
    expect(
      screen.getByText(programWithInjectedStyle.description).textContent,
    ).toBe(programWithInjectedStyle.description);
    expect(typeChip.textContent).toBe(programWithInjectedStyle.type);

    const maintenance = TOKENS_MD_PROGRAM_TYPE_COLORS.Maintenance;
    expect(avatar.style.color).toBe(hexToRgb(maintenance.color));
    expect(avatar.style.backgroundColor).toBe(
      hexToRgb(maintenance.background),
    );
    expect(typeChip.style.color).toBe(hexToRgb(maintenance.color));
    expect(typeChip.style.backgroundColor).toBe(
      hexToRgb(maintenance.background),
    );

    const injectedRgb = hexToRgb("#ff0000");
    expect(avatar.style.color).not.toBe(injectedRgb);
    expect(avatar.style.backgroundColor).not.toBe(injectedRgb);
    expect(container.innerHTML.toLowerCase()).not.toContain("ff0000");
    expect(container.innerHTML.toLowerCase()).not.toContain(
      injectedRgb.toLowerCase(),
    );
  });
});
