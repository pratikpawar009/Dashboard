import { describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { PersonaDashboardShell } from "./PersonaDashboardShell";
import type { ProgramContextData, SignedInUser } from "@/types/persona";

/**
 * SHP-01-TC-04 (SHP-01-NFR-1) — render-only p95 budget for
 * PersonaDashboardShell.
 *
 * Props are fully resolved before the timed window opens (precondition):
 * the shell performs no I/O of its own, so this measures render cost only,
 * never the upstream session/persona-resolver fetch time owned by the
 * composing pages.
 *
 * No global `setupFiles`/`afterEach` cleanup is configured for this runner
 * (see ProgramContext.test.tsx), and a single `it()` drives all 30
 * iterations itself, so `cleanup()` is called per-iteration, inside the
 * loop but AFTER each measurement — never inside the timed window, and
 * never relying on an implicit afterEach that would only fire once the
 * whole test finishes.
 *
 * No warm-up renders: each of the four persona dashboards mounts this shell
 * cold (a fresh page navigation), not warm, so an un-measured warm-up
 * iteration would understate the number a real user actually experiences.
 *
 * p95 method: nearest-rank over the 30 sorted samples
 * (`index = ceil(0.95 * n) - 1`, i.e. the 29th-smallest of 30) — chosen over
 * linear interpolation because it always names an actually-observed sample
 * rather than an interpolated value between two.
 */
describe("PersonaDashboardShell (SHP-01-TC-04)", () => {
  it("renders at p95 < 200ms across 30 iterations", () => {
    const signedInUser: SignedInUser = {
      name: "Devon Rao",
      jobTitle: "Staff Engineer",
    };
    const program: ProgramContextData = {
      icon: "🏗️",
      name: "Platform Modernization",
      type: "Migration",
      description: "Core platform upgrade",
    };
    const persona = "architect";

    const ITERATIONS = 30;
    const durations: number[] = [];

    for (let i = 0; i < ITERATIONS; i += 1) {
      const start = performance.now();
      render(
        <PersonaDashboardShell
          signedInUser={signedInUser}
          persona={persona}
          program={program}
        />,
      );
      const end = performance.now();
      // Cleanup unmounts and clears the DOM between iterations — outside
      // the timed window — so accumulated DOM from prior renders never
      // skews later measurements.
      cleanup();
      durations.push(end - start);
    }

    const sorted = [...durations].sort((a, b) => a - b);
    const p95Index = Math.ceil(0.95 * ITERATIONS) - 1;
    const p95 = sorted[p95Index];

    // Recorded on stdout so the observed number is on record, not just the
    // pass/fail outcome (evidence-pass requirement).
    console.log(
      `PersonaDashboardShell render p95 (nearest-rank, n=${ITERATIONS}): ${p95.toFixed(3)}ms`,
    );

    expect(p95).toBeLessThan(200);
  });
});
