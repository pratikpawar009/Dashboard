# AUTH-05 — Agent flags

All flags raised this session were triaged via `/arh-human-review AUTH-05`. The verdicts, rationales,
and `decided_by`/`decided_at` are the authoritative record and live in `state.json` `.agent_flags[]`;
the three deferrals are linked to rows in `.pending_carry_forward[]`.

| Flag | Kind | Summary | Verdict | Carry-forward |
|---|---|---|---|---|
| AF-01 | runtime-constraint | Next.js seals the cookie jar during a Server Component render, so `page.tsx` cannot persist a refreshed token pair; `writeSession`/`clearSession` tolerate the sealed jar rather than throwing | defer | `server-component-refresh-not-persisted` |
| AF-02 | artefact-drift | TC-02's prose and AC-3 describe a return-URL redirect that D-04 deliberately does not implement | defer | `tc02-ac3-return-url-prose-drift` |
| AF-03 | coverage-gap | `/auth/refresh` always round-trips to real Keycloak, so a dev-bypass refresh token can never complete a successful refresh locally | defer | `dev-bypass-refresh-unverifiable-locally` |
| AF-04 | evidence-na | `design_check` N/A — key empty in `project-commands.yaml`, story is `design: n/a` with no rendered UI | reject | — |
| AF-05 | evidence-na | `runtime` web stack booted clean but `render_check` unavailable — `test_e2e` is empty, no browser tooling | reject | — |

<!-- triaged 2026-09-04 by pawar.pratik0903@gmail.com -->
