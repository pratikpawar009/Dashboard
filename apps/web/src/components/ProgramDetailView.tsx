"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  fetchProgramDetail,
  fetchPrograms,
  type ProgramDetailResult,
} from "@/lib/programDetailApi";
import type { ProgramSwitcherEntry } from "@/types/programDetail";

import { ProgramDetailHeader } from "./ProgramDetailHeader";
import { ProgramSummaryCards } from "./ProgramSummaryCards";
import { ProgramDetailErrorPanel } from "./ProgramDetailErrorPanel";
import styles from "./ProgramDetailView.module.css";

export interface ProgramDetailViewProps {
  initialProgramId: string;
  initialResult: ProgramDetailResult;
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
 */
export function ProgramDetailView({
  initialProgramId,
  initialResult,
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
      // stale response rather than overwrite fresher state.
      if (requestId !== latestSwitchRequestId.current) {
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
          <ProgramSummaryCards
            state={isSwitching ? "loading" : "populated"}
            cards={result.data.summary}
          />
        ) : (
          <ProgramDetailErrorPanel />
        )}
      </div>
    </div>
  );
}
