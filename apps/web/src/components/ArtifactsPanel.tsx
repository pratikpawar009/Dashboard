"use client";

import { useEffect, useRef, useState } from "react";

import type { ArtifactItemData } from "@/types/artifacts";
import { fetchProgramArtifacts } from "@/lib/artifactsApi.client";

import styles from "./ArtifactsPanel.module.css";

/** DESIGN.md § List construct: `hint-placeholder-count="5"` is a contract,
 * not a sample size -- `items` is always exactly 5 entries (SHP-04-FR-1), so
 * this is fixed, not derived from a page size or range like
 * `ProgramTeamPanel`'s `PLACEHOLDER_ROW_COUNT`. */
const PLACEHOLDER_ROW_COUNT = 5;

/**
 * "Artifacts generated" panel (SHP-04 T-12, DESIGN.md § Region ARTIFACTS).
 *
 * Left card of the `ARTIFACTS + RELEASES` two-up section on the Architect /
 * Developer / Product Manager dashboards -- this component only, not the
 * Releases card beside it, and not the parent grid's composition (both
 * belong to ARC-01/DEV-01/PMD-01, D-04). Standalone and unwired: no page
 * imports it yet.
 *
 * Header copy is a static literal, never bound -- "Artifacts generated" /
 * "Outputs produced on this program" carries no program name interpolation
 * (DESIGN.md § Panel header).
 *
 * Self-fetching client component, mirroring `ProgramTeamPanel`'s fetch-guard
 * idiom (latest-request-wins) but with no range state -- this endpoint takes
 * no `range` query param. Fetches via `@/lib/artifactsApi.client`'s
 * `fetchProgramArtifacts()`, the client-side counterpart of
 * `@/lib/artifactsApi`'s server-only version (ADR-0008: a client component
 * never reaches FastAPI directly or holds a token).
 *
 * States (DESIGN.md § States): `loading` renders exactly
 * `PLACEHOLDER_ROW_COUNT` (5) skeleton rows at populated geometry, text
 * suppressed. `ok` always renders exactly 5 rows in wire order -- order is
 * the contract, never re-sorted client-side. There is no dedicated "empty"
 * state: a zero-count row renders the digit `0` like any other value, never
 * hidden or dimmed (AC-3) -- the populated branch handles this by construction,
 * since every row in `items` always renders regardless of `count`. `error`
 * (network/5xx) and `unauthorized` (403, AC-2) both render nothing beyond an
 * inline notice -- DESIGN.md's "panel absent from the page" applies at the
 * parent-page-composition level, which this standalone component does not
 * own; here a `403`/network failure still needs *some* rendering so the
 * component never silently returns null.
 *
 * Row semantics: a `<dl>` per DESIGN.md § Keyboard and assistive tech -- five
 * label/value pairs (`<dt>` = chip + name, `<dd>` = count), not a flat
 * `<div>` stack, so a screen reader gets the `Test cases` / `136`
 * relationship. The tag chip is `aria-hidden` (decorative abbreviation,
 * redundant with the adjacent full-contrast `name` -- colour is never the
 * sole indicator of type). No interactive affordance anywhere -- no
 * `tabindex`, no `role="button"`, no click handler (DESIGN.md § Keyboard and
 * assistive tech: "the panel is entirely non-interactive").
 */
export function ArtifactsPanel({ programId }: { programId: string }) {
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [items, setItems] = useState<ArtifactItemData[]>([]);

  const latestRequestId = useRef(0);

  useEffect(() => {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchProgramArtifacts(programId).then((result) => {
      if (requestId !== latestRequestId.current) {
        return;
      }
      if (result.status === "ok") {
        setItems(result.data.items);
        setStatus("ok");
      } else {
        setStatus("error");
      }
    });
  }, [programId]);

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div className={styles.title}>Artifacts generated</div>
        <div className={styles.subtitle}>Outputs produced on this program</div>
      </div>
      <div className={styles.listBody}>
        {status === "error" ? (
          <div className={styles.errorPanel} role="alert">
            Couldn&apos;t load artifacts.
          </div>
        ) : status === "ok" ? (
          <dl className={styles.list}>
            {items.map((item, i) => (
              <div className={styles.row} key={`${item.tag}-${i}`}>
                <dt className={styles.rowLabel}>
                  <span
                    className={styles.tag}
                    style={{ background: item.bg, color: item.color }}
                    aria-hidden="true"
                  >
                    {item.tag}
                  </span>
                  <span className={styles.name}>{item.name}</span>
                </dt>
                <dd className={styles.count}>{String(item.count)}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <dl className={styles.list}>
            {Array.from({ length: PLACEHOLDER_ROW_COUNT }).map((_, i) => (
              <div
                className={styles.row}
                key={`placeholder-${i}`}
                data-testid="artifacts-row-skeleton"
                aria-hidden="true"
              >
                <dt className={styles.rowLabel}>
                  <span className={styles.skeletonTag} />
                  <span className={styles.skeletonName} />
                </dt>
                <dd className={styles.skeletonCount} />
              </div>
            ))}
          </dl>
        )}
      </div>
      <span aria-live="polite" className={styles.visuallyHidden}>
        {status === "loading"
          ? "Loading artifacts generated"
          : status === "error"
            ? "Failed to load artifacts generated"
            : "Artifacts generated updated"}
      </span>
    </section>
  );
}
