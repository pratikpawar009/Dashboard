"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  fetchProgramDetail,
  fetchPrograms,
} from "@/lib/programDetailApi.client";
import type {
  ProgramDetailResult,
  ProgramSwitcherEntry,
} from "@/types/programDetail";
import type { Persona, SignedInUser } from "@/types/persona";

import { getProgramStyle } from "@/lib/programStyle";

import { PersonaDashboardShell } from "./PersonaDashboardShell";
import { ProgramDetailHeader } from "./ProgramDetailHeader";
import { ProgramSummaryCards } from "./ProgramSummaryCards";
import { ProgramDetailErrorPanel } from "./ProgramDetailErrorPanel";
import { DailyTokenTrendChart } from "./DailyTokenTrendChart";
import { ReleasesList } from "./ReleasesList";
import styles from "./ProgramDetailView.module.css";

export interface ProgramDetailViewProps {
  initialProgramId: string;
  initialResult: ProgramDetailResult;
  persona?: Persona;
  signedInUser?: SignedInUser;
}

/**
 * Client orchestrator for `/programs/[program_id]` (T-12, FR-4, D-07).
 *
 * Owns the page's mutable state: current `programId`/`result`, whether a
 * switch is in flight (`isSwitching`), and the "Switch program" disclosure's
 * open state and option list. `initialProgramId`/`initialResult` come from
 * `page.tsx`'s server-side fetch (T-13) and seed this state; after that,
 * every update is client-side.
 *
 * Switch-reload (`ProgramSwitcher`'s `onSelect`): calls
 * `fetchProgramDetail(newId, { switchedFrom: <id being left> })` — this is
 * what sends `X-Program-Switch-From` (D-07) — then, on resolve, updates
 * `result` and calls `useRouter().replace(/programs/${newId})`. URL and
 * rendered data update together, client-side; `router.replace` is used
 * (not `router.push`) so switching programs does not grow the back-button
 * history, and `window.location` is never touched (FR-4: no hard reload).
 *
 * `latestSwitchRequestId` guards against out-of-order resolution
 * (`.claude/rules/performance-baseline.md`): if a second switch is issued
 * before the first one's fetch resolves, only the most recently issued
 * request is allowed to write into state.
 *
 * `GET /api/programs` (`fetchPrograms`) is fetched exactly once, on mount,
 * for the switcher's option list — skipped entirely when the initial fetch
 * already 404d (D-03: no valid current program to compare a switcher option
 * against).
 *
 * `persona`/`signedInUser` (PGD-07, optional, additive): forwarded verbatim
 * to `PersonaDashboardShell` for the brand bar's signed-in identity block.
 * Sourced by the caller (`page.tsx`) from `GET /api/me` — this component
 * fetches neither and holds no persona/session state of its own.
 *
 * Auth (AUTH-05, ADR-0008/D-08/D-10): both fetches go through
 * `@/lib/programDetailApi.client`, which calls the frontend's own same-origin
 * `/api/proxy/*` Route Handlers. This component never reaches FastAPI
 * directly and holds no token, cookie, or session concept of any kind — the
 * proxy resolves the access token server-side, so there is nothing here to
 * attach. An `"unauthorized"` result is therefore terminal rather than
 * retryable: the proxy already exhausted `tokenStore.callWithAuth`'s
 * retry-once before responding (D-10), so the only remaining move is to send
 * the user back through sign-in.
 */
export function ProgramDetailView({
  initialProgramId,
  initialResult,
  persona,
  signedInUser,
}: ProgramDetailViewProps) {
  const router = useRouter();

  const [programId, setProgramId] = useState(initialProgramId);
  const [result, setResult] = useState<ProgramDetailResult>(initialResult);
  const [isSwitching, setIsSwitching] = useState(false);
  const [isSwitcherOpen, setIsSwitcherOpen] = useState(false);
  const [switcherOptions, setSwitcherOptions] = useState<
    ProgramSwitcherEntry[]
  >([]);
  const [isLoadingOptions, setIsLoadingOptions] = useState(
    initialResult.status !== "not_found",
  );

  const latestSwitchRequestId = useRef(0);

  useEffect(() => {
    if (initialResult.status === "not_found") {
      return;
    }
    let cancelled = false;
    fetchPrograms().then((options) => {
      if (!cancelled) {
        setSwitcherOptions(options);
        setIsLoadingOptions(false);
      }
    });
    return () => {
      cancelled = true;
    };
    // `initialResult.status` is fixed for this component's lifetime (T-13
    // passes it once, per navigation); this intentionally runs only once.
  }, [initialResult.status]);

  function handleSelect(newProgramId: string) {
    const requestId = ++latestSwitchRequestId.current;
    const previousProgramId = programId;

    setIsSwitching(true);
    setIsSwitcherOpen(false);

    fetchProgramDetail(newProgramId, {
      switchedFrom: previousProgramId,
    }).then((nextResult) => {
      // A newer switch was issued before this one resolved -- discard the
      // stale response rather than overwrite fresher state. This guard runs
      // BEFORE the `unauthorized` branch below on purpose: a superseded
      // in-flight request must never be able to navigate the browser away.
      if (requestId !== latestSwitchRequestId.current) {
        return;
      }

      // AUTH-05 AC-8/FR-5, client-side half. The proxy already exhausted
      // `callWithAuth`'s retry-once server-side (D-10), so this is terminal:
      // re-authenticate. `window.location.href` rather than `router.push` is
      // deliberate -- re-auth must be a full document navigation out of the
      // React tree and into the `/login` Route Handler's redirect chain, not
      // a client-side route transition. FR-4's "no hard reload" rule governs
      // the switcher's happy path (below), not this bail-out.
      //
      // Nothing else is updated on the way out: leaving `isSwitching` set
      // keeps the loading state up while the navigation lands, where flipping
      // back to a populated view would flash stale content first.
      if (nextResult.status === "unauthorized") {
        window.location.href = "/login";
        return;
      }

      setResult(nextResult);
      setProgramId(newProgramId);
      setIsSwitching(false);
      router.replace(`/programs/${newProgramId}`);
    });
  }

  const headerState: "populated" | "loading" | "error" = isSwitching
    ? "loading"
    : result.status === "ok"
      ? "populated"
      : "error";

  return (
    // FR-2 / AC-2: `program` is explicitly `undefined` here, never the real
    // program object. PersonaDashboardShell's own header region is gated on
    // `program !== undefined` — ProgramDetailHeader below already ships the
    // mockup's <!-- HEADER --> region (program avatar/name/type-chip/
    // description), so passing a real `program` here would double-render it.
    <PersonaDashboardShell program={undefined} persona={persona} signedInUser={signedInUser}>
      <div className={styles.wrapper}>
        {/* AF-05: BackToProgramBoard now renders inside ProgramDetailHeader's
            sticky wrapper (DESIGN.md Region 1, mockup L389 first child), not
            as a sibling here — it must scroll pinned with the identity row. */}
        <ProgramDetailHeader
          state={headerState}
          header={result.status === "ok" ? result.data.header : undefined}
          switcher={{
            options: switcherOptions,
            currentProgramId: programId,
            isOpen: isSwitcherOpen,
            onToggle: () => setIsSwitcherOpen((open) => !open),
            onSelect: handleSelect,
            isLoadingOptions,
          }}
        />
        <div className={styles.content}>
          {result.status === "ok" ? (
            <>
              <ProgramSummaryCards
                state={isSwitching ? "loading" : "populated"}
                cards={result.data.summary}
              />
              {/* T-13, DESIGN.md § Layout: sibling card below the summary
                  strip, reusing the header's already-resolved program-type
                  accent color rather than picking its own (DESIGN.md § Chart
                  area). Gated on the same `result.status === "ok"` check as
                  ProgramSummaryCards above -- the error branch is unaffected. */}
              <DailyTokenTrendChart
                programId={programId}
                accentColor={
                  getProgramStyle(result.data.header.type).avatarStyle
                    .color as string
                }
              />
              {/* T-15, PLAN.md § Navigation/routing map: mounted immediately
                  after DailyTokenTrendChart, between it and the not-yet-built
                  Commands+Team section. Gated on the same
                  `result.status === "ok"` check. */}
              <ReleasesList programId={programId} />
            </>
          ) : (
            <ProgramDetailErrorPanel />
          )}
        </div>
      </div>
    </PersonaDashboardShell>
  );
}
