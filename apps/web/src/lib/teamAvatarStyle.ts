/**
 * `member_name` + `role` -> `{ initials, avBg }` (PGD-05 T-15, DESIGN.md
 * § "Avatar colour and initials -- not supplied by this story's API").
 *
 * `ProgramTeamRow` (PGD-05-FR-2) locks five fields and explicitly excludes
 * `avBg`/`initials` -- both are renderer-owned derivations from
 * `member_name`/`role`, not API data. Mirrors `programStyle.ts`'s
 * `getProgramStyle()` shape (role/type -> color lookup with a documented
 * fallback), but returns `avBg` as a plain string (not a `CSSProperties`
 * pair) since the avatar circle here only ever needs a background color, no
 * paired text color.
 */

/**
 * Derives initials from `member_name`: first letter of the first token +
 * first letter of the last token, uppercased (DESIGN.md: "two-letter
 * first+last initial is what every sample shows, e.g. `Devon Rao -> DR`").
 * A single-token name uses that token's first letter twice is avoided --
 * single-token names fall back to just that one letter, and an empty/
 * unresolved name renders a neutral placeholder character rather than
 * inventing shipped sample copy (DESIGN.md: "Sample names are never
 * shipped ... An unresolved `member_name` renders a neutral state").
 */
export function getInitials(memberName: string): string {
  const parts = memberName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].charAt(0).toUpperCase();
  }
  const first = parts[0].charAt(0);
  const last = parts[parts.length - 1].charAt(0);
  return `${first}${last}`.toUpperCase();
}

/**
 * `role` -> avatar background color, sourced from `docs/design/tokens.md`
 * § Persona colors (F-22 adds the `QA Engineer` entry this map reads).
 * An unrecognized role falls back to the `Developer` entry -- matching
 * `getProgramStyle()`'s "unrecognized value degrades to a named fallback,
 * never throws" convention (`programStyle.ts`), since a per-person avatar
 * color is a display default, not a fail-loud invariant.
 */
export function getAvatarBackground(role: string): string {
  return ROLE_AVATAR_COLORS[role] ?? ROLE_AVATAR_COLORS["Developer"];
}

const ROLE_AVATAR_COLORS: Record<string, string> = {
  Architect: "#6a4fd0",
  Developer: "#2a6fdb",
  "Product Manager": "#d97757",
  "Eng Manager": "#1f8a5b",
  // DESIGN.md § "Avatar colour and initials": the mockup's `QA Engineer`
  // avatar color has no home in `docs/design/tokens.md` § Persona colors --
  // added there (F-22) rather than hardcoded here as a bare, untokenised hex.
  "QA Engineer": "#d1495b",
};
