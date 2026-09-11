import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/**
 * T-13 -- source-scan regression guard for condition C-2(a) (PLAN.md § 6):
 * T-10 relocated the OAuth relay from `/login` to `/login/start` so T-11's
 * branded sign-in page could occupy `/login`. This is NOT a render test --
 * no component is mounted here -- it is a plain `fs.readFileSync` scan
 * asserting the shipped call sites that navigate to `/login` are byte-level
 * unchanged by that move, mirroring the structural-check idiom already used
 * by `ProgramDetailView.authFlow.test.tsx` (readFileSync + fileURLToPath to
 * resolve paths relative to this file, rather than a project-wide source-scan
 * test helper -- no such shared helper exists in this codebase yet).
 *
 * **The "7 vs 5" discrepancy (recorded, not papered over)**: the story
 * (`docs/stories/OVW-05.md` AC-17 decision-log entry) and the research report
 * both say "7" shipped `redirect("/login")` call sites. A source grep on
 * 2026-09-11 (PLAN.md § 6, condition C-2 note) found only **5** in shipped,
 * non-test, non-comment source. This file asserts exactly those 5 -- the
 * remaining 2 were not invented to make the prose's number come out right.
 *
 * Two OTHER files changed their `/login` reference as part of this same
 * relocation, but are deliberately NOT among the 5 asserted below:
 * `ProgramDetailView.authFlow.test.tsx` and `tokenStore.security.test.ts`
 * updated a *module import path* (`@/app/login/route` -> `@/app/login/start/route`),
 * not a `/login` navigation call site -- out of scope for this guard.
 */

const currentDir = path.dirname(fileURLToPath(import.meta.url));

function readSource(...segments: string[]): string {
  return readFileSync(path.join(currentDir, ...segments), "utf-8");
}

describe('existing redirect("/login") call sites stay unchanged (condition C-2(a))', () => {
  it('apps/web/src/app/programs/[program_id]/page.tsx still calls redirect("/login") on session expiry, not "/login/start"', () => {
    const source = readSource("..", "programs", "[program_id]", "page.tsx");
    expect(source).toContain('redirect("/login")');
    expect(source).not.toContain('redirect("/login/start")');
  });

  it('apps/web/src/app/overview/page.tsx still calls redirect("/login") on session expiry, not "/login/start"', () => {
    const source = readSource("..", "overview", "page.tsx");
    expect(source).toContain('redirect("/login")');
    expect(source).not.toContain('redirect("/login/start")');
  });

  it('apps/web/src/app/callback/route.ts still relays both failure paths to NextResponse.redirect(new URL("/login", request.url)), exactly twice, not "/login/start"', () => {
    const source = readSource("..", "callback", "route.ts");
    const literal = 'NextResponse.redirect(new URL("/login", request.url))';
    const occurrences = source.split(literal).length - 1;
    expect(occurrences).toBe(2);
    expect(source).not.toContain('new URL("/login/start"');
  });

  it('apps/web/src/components/ProgramDetailView.tsx still hard-navigates via window.location.href = "/login" on a superseded/unauthorized switch, not "/login/start"', () => {
    const source = readSource(
      "..",
      "..",
      "components",
      "ProgramDetailView.tsx",
    );
    expect(source).toContain('window.location.href = "/login"');
    expect(source).not.toContain('window.location.href = "/login/start"');
  });

  it("the T-10 relay move actually happened: login/route.ts is gone, login/start/route.ts exists", () => {
    expect(existsSync(path.join(currentDir, "route.ts"))).toBe(false);
    expect(existsSync(path.join(currentDir, "start", "route.ts"))).toBe(true);
  });
});
