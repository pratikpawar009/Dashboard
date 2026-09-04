import type { ProgramDetailHeaderData } from "@/types/programDetail";
import { getProgramStyle } from "@/lib/programStyle";
import { BackToProgramBoard } from "./BackToProgramBoard";
import { ProgramSwitcher, type ProgramSwitcherProps } from "./ProgramSwitcher";
import styles from "./ProgramDetailHeader.module.css";

export interface ProgramDetailHeaderProps {
  state: "populated" | "loading" | "error";
  header?: ProgramDetailHeaderData;
  switcher: ProgramSwitcherProps;
}

/**
 * Sticky program-detail header (AC-2, DESIGN.md Region 2) — avatar, name,
 * type chip, description, plus the switch-program control (Region 3,
 * delegated to `ProgramSwitcher`).
 *
 * `avatarStyle`/`typeChip` are derived client-side via the existing, already
 * -tested `getProgramStyle(type)` (D-05) — `header` itself carries only
 * `{icon, name, type, description}`, same split as `ProgramContext.tsx`.
 *
 * The mockup's static `CIO / CXO` persona chip (L396, sibling of the type
 * chip) is deliberately NOT rendered here (D-01): AC-6 forbids persona
 * branching in this shell and there is no data source for it. Do not
 * "restore" it as a missing element — it is a design gap the Product Gate
 * already resolved.
 *
 * `state === 'error'` (D-03): renders only the sticky wrapper + the fallback
 * line "Program not found" — no avatar/name/chip/description, and no
 * `ProgramSwitcher` at all (its own `GET /api/programs` fetch is skipped
 * entirely in this state; there is no valid current program to compare
 * against for the active-row highlight).
 *
 * `state === 'loading'`: keeps the populated geometry (avatar box, name,
 * type-chip, description all mount) but suppresses their text content — the
 * mockup has no skeleton treatment for this region (DESIGN.md States table).
 *
 * AF-05: `BackToProgramBoard` (DESIGN.md Region 1, mockup `<!-- HEADER -->`
 * L389) is the first child inside this component's sticky wrapper in every
 * state, matching the mockup's `<header>` (L388-422) — the link is meant to
 * pin on scroll with the identity/switcher row, not scroll away as a
 * `ProgramDetailView`-level sibling above it. Do not hoist it back out.
 */
export function ProgramDetailHeader({
  state,
  header,
  switcher,
}: ProgramDetailHeaderProps) {
  if (state === "error") {
    return (
      <div className={styles.header}>
        <BackToProgramBoard />
        <span
          className={styles.errorText}
          data-testid="program-detail-header-error-text"
        >
          Program not found
        </span>
      </div>
    );
  }

  const { avatarStyle, typeChip } = header
    ? getProgramStyle(header.type)
    : { avatarStyle: undefined, typeChip: undefined };

  return (
    <div className={styles.header}>
      <BackToProgramBoard />
      <div className={styles.content}>
        <div className={styles.row}>
          <div
            className={styles.avatar}
            style={avatarStyle}
            data-testid="program-detail-header-avatar"
          >
            {state === "populated" ? header?.icon : null}
          </div>
          <div className={styles.details}>
            <div className={styles.titleRow}>
              <div
                className={styles.name}
                data-testid="program-detail-header-name"
              >
                {state === "populated" ? header?.name : null}
              </div>
              {/* D-01: the mockup's static `CIO / CXO` persona chip (L396) is
                  deliberately omitted here — see the file-level doc comment. */}
              <span
                className={styles.typeChip}
                style={typeChip}
                data-testid="program-detail-header-type-chip"
              >
                {state === "populated" ? header?.type : null}
              </span>
            </div>
            <div
              className={styles.description}
              data-testid="program-detail-header-description"
            >
              {state === "populated" ? header?.description : null}
            </div>
          </div>
        </div>
        <ProgramSwitcher {...switcher} />
      </div>
    </div>
  );
}
