## Q-01 (T-16) — `ProgramTeamRow` carries no member identifier, so the popup cannot address a member

**Raised by**: T-16 (implementation-agent), escalated by the orchestrator after verification.
**Severity**: blocks AC-9 correctness. Not a cosmetic gap.

**The gap**: `ProgramTeamRow` is locked to exactly 5 fields by PGD-05-FR-2 / research condition
C-4 — `member_name, role, sessions, tokens, avg_tokens_per_session`. None of them is a stable
member identifier. But the popup's whole path is keyed on one:
`member_in_program_visibility(current_user, program_id, target_member_id)` and
`fetch_card_totals(db, user_id)` both need `user_id`.

**What T-16 did as an interim**: passed `member_name` as the `memberId` argument.

**Why that is not safe** (verified, not assumed):
- `services/api/app/core/rbac.py:177` — the gate's self-check is
  `if target_member_id == current_user.user_id`. A display name never equals a user id, so a
  user opening their OWN popup falls through to the persona branch and is **denied 403 on their
  own data** unless they happen to be `cio`. That directly contradicts AC-9 ("when the requester
  is M themself ... then clicking the row opens the popup").
- `services/api/app/models/rollup.py:124-125` — `program_members` carries `user_id` AND `name`
  as separate columns, so the identifier exists in the source table; `fetch_program_team()`
  reads it and discards it before building the row.
- Downstream, SHP-02's service functions would be called with a name as `user_id`, returning
  empty data rather than the member's usage.

**Options**:
1. Add a 6th field (`member_id` / `user_id`) to `ProgramTeamRow`. Correct and cheap — the value
   is already in hand — but it changes a field set locked by FR-2/C-4 and named in
   `docs/requirements/api.md`, `README.md`, the TS wire types, and 5 downstream consumers'
   expectations (ARC-01, DEV-01, PMD-01, EMD-01, SHP-07). Needs FR-2/C-4 amended, not ignored.
2. Add a separate lookup the popup calls to resolve name → user_id. Avoids touching the locked
   shape but adds a round-trip and a second source of truth for identity.
3. Keep names out of the URL entirely and have the popup route accept a row index or opaque
   handle — larger change, no precedent in this codebase.

**Recommendation**: option 1. The row schema was locked before the popup was folded into this
story (RTM 2026-08-26), so the lock predates the requirement that broke it.

**Status**: OPEN — T-16's popup should not ship on the `member_name` interim.

**RESOLVED 2026-09-17** (user decision: option 1). `member_id: str` added to `ProgramTeamRow`
as the FIRST field, populated from the `user_id` the roster SELECT already reads — no new
query, D-01's two-SELECT contract intact (perf test still 2 SELECTs across all three ranges).
Propagated to the service, TS wire types, `ProgramTeamPanel` (passes `row.member_id` as
identity; `member_name` stays display-only for the accessible label), `api.md`, `README.md`,
and the affected tests. Recorded as DECISIONS.md D-06. Verified: schema line 1 of the row,
`program_team.py:84`, `ProgramTeamPanel.tsx:256`.
