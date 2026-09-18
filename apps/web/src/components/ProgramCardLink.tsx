"use client";

import type { CSSProperties, ReactNode } from "react";

import styles from "./ProgramCard.module.css";

/**
 * Client leaf for `ProgramCard`'s root `<a>` (OVW-04-AC-1/AC-3, D-06).
 *
 * Extracted so `ProgramCard` itself can stay a Server Component — mirrors
 * this codebase's existing split between a small `"use client"` interactive
 * leaf and a larger server-rendered parent (`ProgramSwitcher.tsx` is the
 * precedent this follows, rather than converting the whole card subtree
 * to a Client Component, which would also ship `ProgramSparkline`'s SVG
 * rendering to the browser bundle for every one of up to 20 cards).
 *
 * Owns only the click handler needed for D-06's `program_drilldown`
 * telemetry — `console.info(JSON.stringify(...))` — without blocking or
 * delaying navigation (no `preventDefault()`), matching the backend's own
 * `logger.info("program_drilldown", extra={...})` shape until a real
 * frontend telemetry pipe exists.
 */
export function ProgramCardLink({
  href,
  programId,
  borderLeftColor,
  ariaLabel,
  children,
}: {
  href: string;
  programId: string;
  borderLeftColor: CSSProperties["borderLeftColor"];
  ariaLabel: string;
  children: ReactNode;
}) {
  function handleClick() {
    // D-06: no frontend telemetry sink exists yet; structured console.info
    // matches JSONFormatter's field names until one does.
    console.info(JSON.stringify({ event: "program_drilldown", program_id: programId }));
  }

  return (
    <a
      href={href}
      className={styles.card}
      style={{ borderLeftColor }}
      aria-label={ariaLabel}
      onClick={handleClick}
    >
      {children}
    </a>
  );
}
