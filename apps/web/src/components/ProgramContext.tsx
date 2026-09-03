import type { ProgramContextData } from "@/types/persona";
import { getProgramStyle } from "@/lib/programStyle";
import styles from "./ProgramContext.module.css";

/**
 * Program-context block (FR-4) — icon/name/type-chip/description, verbatim
 * from the `program` prop.
 *
 * The component destructures exactly `{ icon, name, type, description }` off
 * `program`, so an extraneous field on the prop object (e.g. an injected
 * `avatarStyle`) is never read. `avatarStyle`/`typeChip` are instead composed
 * internally from `getProgramStyle(type)` (D-04/D-06), which sources its
 * color pair from `docs/design/tokens.md` § Program type colors — never from
 * the prop (research conditions C-3/C-5, `SHP-01-TC-03`). All static
 * geometry lives in `ProgramContext.module.css`; only the data-driven
 * `{ color, background }` pair crosses via `style`.
 *
 * Owns no loading or empty state: the composing page resolves `program`
 * fully before render (C-3). An absent/undefined `program` is a caller
 * error, not a state this component renders.
 */
export function ProgramContext({ program }: { program: ProgramContextData }) {
  const { icon, name, type, description } = program;
  const { avatarStyle, typeChip } = getProgramStyle(type);

  return (
    <div className={styles.container}>
      <div className={styles.avatar} style={avatarStyle}>
        {icon}
      </div>
      <div className={styles.details}>
        <div className={styles.titleRow}>
          <div className={styles.name}>{name}</div>
          <span className={styles.typeChip} style={typeChip}>
            {type}
          </span>
        </div>
        <div className={styles.description}>{description}</div>
      </div>
    </div>
  );
}
