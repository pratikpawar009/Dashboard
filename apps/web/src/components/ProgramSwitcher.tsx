"use client";

import type { CSSProperties } from "react";

import type { ProgramSwitcherEntry } from "@/types/programDetail";
import styles from "./ProgramSwitcher.module.css";

export interface ProgramSwitcherProps {
  options: ProgramSwitcherEntry[];
  currentProgramId: string;
  isOpen: boolean;
  onToggle: () => void;
  onSelect: (programId: string) => void;
  isLoadingOptions: boolean;
}

/**
 * Parses a pre-formatted CSS declaration string (e.g. `"background-color:
 * #0f1a2e;"`, `services/api/app/utils/format.py::dot_style_for_program`,
 * ADR-0005) into a React inline-style object. `dotStyle` ships as data and
 * the mockup binds it straight into a template's `style` attribute as a raw
 * string -- React's `style` prop does not accept a string, so this is the
 * minimal client-side translation needed to bind it verbatim (not a
 * re-derivation of the value itself).
 */
function dotStyleToInlineStyle(dotStyle: string): CSSProperties {
  const style: CSSProperties = {};
  const match = /^([a-zA-Z-]+)\s*:\s*(.+?);?$/.exec(dotStyle);
  if (!match) {
    return style;
  }
  const [, cssProperty, cssValue] = match;
  const camelCaseProperty = cssProperty.replace(
    /-([a-z])/g,
    (_full, letter: string) => letter.toUpperCase(),
  );
  (style as Record<string, string>)[camelCaseProperty] = cssValue.trim();
  return style;
}

/**
 * "Switch program" disclosure control (AC-5, DESIGN.md Region 3).
 *
 * Controlled by the parent (`ProgramDetailView`, T-12): `isOpen`/`onToggle`
 * own open/closed state, `onSelect` is called with the chosen `program_id`
 * and never navigates natively -- every row is a `role="menuitem"` `<button>`,
 * not an `<a>`, so a selection can never fire a native navigation that the
 * FR-4 client-side reload would have to fight.
 *
 * The trigger is a real `<button>` -- Enter/Space activation is native
 * browser behavior, no `onKeyDown` hack is added here.
 *
 * `rowStyle`/`current` (ADR-0005 §2) are computed here, from `currentProgramId`
 * and each row's own `program_id` -- never sourced from the API. When
 * `options` is empty (`fetchPrograms()` degraded to `[]`) or still loading,
 * the trigger renders `disabled` instead of an openable, empty menu.
 */
export function ProgramSwitcher({
  options,
  currentProgramId,
  isOpen,
  onToggle,
  onSelect,
  isLoadingOptions,
}: ProgramSwitcherProps) {
  const currentOption = options.find(
    (option) => option.program_id === currentProgramId,
  );
  const isDisabled = isLoadingOptions || options.length === 0;
  const menuIsRenderable = isOpen && !isDisabled;

  return (
    <div className={styles.wrapper}>
      <span className={styles.label}>Switch program</span>
      <div className={styles.control}>
        <button
          type="button"
          className={
            isOpen ? `${styles.trigger} ${styles.triggerOpen}` : styles.trigger
          }
          aria-haspopup="true"
          aria-expanded={isOpen}
          disabled={isDisabled}
          onClick={onToggle}
        >
          {currentOption && (
            <span
              className={styles.dot}
              style={dotStyleToInlineStyle(currentOption.dotStyle)}
            />
          )}
          <span className={styles.currentName}>
            {currentOption?.label ?? ""}
          </span>
          <span
            className={styles.caret}
            style={{ transform: isOpen ? "rotate(180deg)" : "rotate(0deg)" }}
          >
            ▾
          </span>
        </button>
        {menuIsRenderable && (
          <div role="menu" className={styles.menu}>
            {options.map((option) => {
              const isCurrent = option.program_id === currentProgramId;
              return (
                <button
                  key={option.program_id}
                  type="button"
                  role="menuitem"
                  className={
                    isCurrent ? `${styles.row} ${styles.rowCurrent}` : styles.row
                  }
                  onClick={() => onSelect(option.program_id)}
                >
                  <span
                    className={styles.dot}
                    style={dotStyleToInlineStyle(option.dotStyle)}
                  />
                  <span className={styles.rowLabel}>{option.label}</span>
                  {isCurrent && <span className={styles.check}>✓</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
