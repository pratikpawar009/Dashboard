"use client";

import { useEffect, useRef, useState } from "react";

import type { PersonalSessionsData } from "@/types/personalSessions";
import { fetchPersonalSessions } from "@/lib/personalSessionsApi.client";

import styles from "./SessionsTable.module.css";

/** DESIGN.md § Scroll body: `hint-placeholder-count="20"` corroborates
 * `page_size = 20` as the default, and is also the loading-state skeleton
 * row count -- mirrors `ArtifactsPanel.tsx`'s `PLACEHOLDER_ROW_COUNT` idiom. */
const PAGE_SIZE = 20;
const PLACEHOLDER_ROW_COUNT = 20;
const DEFAULT_PAGE = 1;

/**
 * "Your session-wise usage" panel (SHP-03 T-15, DESIGN.md § Anatomy).
 *
 * Self-fetching client component -- mirrors `ArtifactsPanel`'s fetch-guard
 * idiom (latest-request-wins via a ref) since, like that panel, there is no
 * `range` query param here; pagination is server-side via `page`/`page_size`
 * (DESIGN.md § Divergences D-2). Fetches via
 * `@/lib/personalSessionsApi.client`'s `fetchPersonalSessions()` (T-14).
 *
 * Standalone and unwired (DESIGN.md § Scope): no page imports this yet --
 * ARC-01/DEV-01/PMD-01 mount it later.
 *
 * Subtitle / `prog.name` (DESIGN.md § Divergences D-3): the mockup's header
 * interpolates `{{ prog.name }}`, but this story's API is a cross-program
 * aggregate with no `program_id` in the payload -- SHP-03 must not invent a
 * program field to satisfy that binding. Decision: accept an optional
 * `programName` prop and render the full "Your recent sessions on {name}"
 * subtitle only when the parent supplies one; omit the subtitle entirely
 * when it doesn't, rather than rendering a broken or placeholder string.
 * This keeps the binding available for ARC-01/DEV-01/PMD-01 (which do have
 * program context) without this component inventing or guessing a value.
 *
 * Empty state (DESIGN.md § Divergences D-4, not drawn by the mockup):
 * `items: []` renders a single centered "No sessions yet." message in the
 * scroll body, mirroring `ReleasesList`'s empty-copy-only treatment, and
 * suppresses the footer's pagination controls (nothing to paginate).
 *
 * Denied / error state (DESIGN.md § Divergences D-5, not drawn by the
 * mockup): both a 403 (`denied`) and a network/5xx (`error`) render a single
 * inline notice in place of the scroll body, mirroring `ArtifactsPanel`'s
 * `errorPanel` treatment -- `denied` and `error` get distinct copy so a
 * cross-user access issue doesn't read as "try again", but share the same
 * layout since neither has a retry-able mockup precedent (unauthorized is
 * terminal -- `fetchPersonalSessions` never resolves `unauthorized`
 * separately from `error` past this component's own status handling; it's
 * folded into `error` here since there is no distinct 401 treatment DESIGN.md
 * specifies and this is a personal panel behind an already-authenticated
 * shell).
 *
 * Accessibility (DESIGN.md § Accessibility -- exceeding the mockup's bare
 * `<div>` grid): a real `<table>` associates `Session`/`Duration`/`Tokens`
 * headers with their cells; `‹`/`›` pagination buttons carry accessible
 * names via `aria-label`; the current page button carries
 * `aria-current="page"`; the scroll body is a natively-focusable
 * `tabIndex={0}` region so it's keyboard-reachable; truncated session
 * titles keep the full text available via a `title` attribute.
 *
 * Values (`title`, `meta`, `duration`, `tokens`) arrive pre-formatted from
 * the API (DESIGN.md § Value formats) -- this component formats nothing.
 */
export function SessionsTable({
  userId,
  programName,
}: {
  userId: string;
  programName?: string;
}) {
  const [page, setPage] = useState(DEFAULT_PAGE);
  const [status, setStatus] = useState<"loading" | "ok" | "denied" | "error">(
    "loading",
  );
  const [data, setData] = useState<PersonalSessionsData | undefined>(undefined);

  const latestRequestId = useRef(0);

  function load(nextPage: number) {
    const requestId = ++latestRequestId.current;
    setStatus("loading");
    fetchPersonalSessions(userId, nextPage, PAGE_SIZE).then((result) => {
      if (requestId !== latestRequestId.current) {
        return;
      }
      if (result.status === "ok") {
        setData(result.data);
        setStatus("ok");
      } else if (result.status === "denied") {
        setStatus("denied");
      } else {
        setStatus("error");
      }
    });
  }

  useEffect(() => {
    load(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, page]);

  const isEmpty = status === "ok" && data !== undefined && data.items.length === 0;
  const totalPages =
    status === "ok" && data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;
  const currentPage = status === "ok" && data ? data.page : page;

  const rangeStart =
    status === "ok" && data && data.total > 0
      ? (data.page - 1) * data.page_size + 1
      : 0;
  const rangeEnd =
    status === "ok" && data ? Math.min(data.page * data.page_size, data.total) : 0;
  const rangeText =
    status === "ok" && data ? `${rangeStart}–${rangeEnd} of ${data.total} sessions` : "";

  return (
    <section className={styles.section}>
      <div className={styles.header}>
        <div className={styles.title}>Your session-wise usage</div>
        {programName ? (
          <div className={styles.subtitle}>
            Your recent sessions on {programName}
          </div>
        ) : null}
      </div>

      {status !== "denied" && status !== "error" && !isEmpty ? (
        <div className={styles.columnHeaderRow} aria-hidden="true">
          <span>Session</span>
          <span className={styles.alignRight}>Duration</span>
          <span className={styles.alignRight}>Tokens</span>
        </div>
      ) : null}

      <div className={styles.scrollBody} tabIndex={0}>
        {status === "denied" ? (
          <div className={styles.noticePanel} role="alert">
            You don&apos;t have access to these sessions.
          </div>
        ) : status === "error" ? (
          <div className={styles.noticePanel} role="alert">
            Couldn&apos;t load sessions.
          </div>
        ) : isEmpty ? (
          <div className={styles.emptyPanel}>No sessions yet.</div>
        ) : status === "ok" && data ? (
          <table className={styles.table}>
            <caption className={styles.visuallyHidden}>
              Your session-wise usage
            </caption>
            <thead>
              <tr>
                <th scope="col" className={styles.thSession}>
                  Session
                </th>
                <th scope="col" className={styles.thDuration}>
                  Duration
                </th>
                <th scope="col" className={styles.thTokens}>
                  Tokens
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((s, i) => (
                <tr className={styles.row} key={`${s.meta}-${i}`}>
                  <td className={styles.sessionCell}>
                    <div className={styles.sessionTitle} title={s.title}>
                      {s.title}
                    </div>
                    <div className={styles.sessionMeta}>{s.meta}</div>
                  </td>
                  <td className={styles.durationCell}>{s.duration}</td>
                  <td className={styles.tokensCell}>{s.tokens}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className={styles.table}>
            <caption className={styles.visuallyHidden}>
              Loading your session-wise usage
            </caption>
            <thead>
              <tr>
                <th scope="col" className={styles.thSession}>
                  Session
                </th>
                <th scope="col" className={styles.thDuration}>
                  Duration
                </th>
                <th scope="col" className={styles.thTokens}>
                  Tokens
                </th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: PLACEHOLDER_ROW_COUNT }).map((_, i) => (
                <tr
                  className={styles.row}
                  key={`placeholder-${i}`}
                  data-testid="sessions-row-skeleton"
                  aria-hidden="true"
                >
                  <td className={styles.sessionCell}>
                    <div className={styles.skeletonTitle} />
                    <div className={styles.skeletonMeta} />
                  </td>
                  <td className={styles.durationCell}>
                    <div className={styles.skeletonDuration} />
                  </td>
                  <td className={styles.tokensCell}>
                    <div className={styles.skeletonTokens} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {status === "ok" && data && !isEmpty ? (
        <div className={styles.footer}>
          <div className={styles.rangeText}>{rangeText}</div>
          <div className={styles.pagination}>
            <button
              type="button"
              className={styles.pageButton}
              aria-label="Previous page"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
            >
              &#8249;
            </button>
            {Array.from({ length: totalPages }).map((_, i) => {
              const pageNum = i + 1;
              const isActive = pageNum === currentPage;
              return (
                <button
                  key={pageNum}
                  type="button"
                  className={
                    isActive
                      ? `${styles.pageButton} ${styles.pageButtonActive}`
                      : styles.pageButton
                  }
                  aria-current={isActive ? "page" : undefined}
                  aria-label={`Page ${pageNum}`}
                  onClick={() => setPage(pageNum)}
                >
                  {pageNum}
                </button>
              );
            })}
            <button
              type="button"
              className={styles.pageButton}
              aria-label="Next page"
              disabled={currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
            >
              &#8250;
            </button>
          </div>
        </div>
      ) : null}

      <span aria-live="polite" className={styles.visuallyHidden}>
        {status === "loading"
          ? "Loading your session-wise usage"
          : status === "denied"
            ? "Access denied to session-wise usage"
            : status === "error"
              ? "Failed to load your session-wise usage"
              : "Your session-wise usage updated"}
      </span>
    </section>
  );
}
