---
name: decide
description: Append a decision entry to the feature's DECISIONS.md log — id, title, blast-radius, reversibility, adr link — the single story-level record of every non-trivial technical choice.
when_to_use: Inside `/arh-plan-implementation` Phase 1, one entry per non-trivial decision. Also when impl-planning-agent or implementation-agent makes a non-trivial choice that wasn't anticipated in PLAN (e.g. picking a library variant mid-implementation). One entry per decision. Trivial choices (variable names, internal helper boundaries) do NOT get an entry.
user-invocable: false
allowed-tools: Read Write Edit
---
# decide — decision-log capture

## Why this skill exists

`docs/features/<id>/DECISIONS.md` is the feature's decision log — the single story-level record of every non-trivial technical choice, the way an SDLC team keeps a decision log beside the design. It is both:

- **Human-readable** — a reviewer in `/arh-review`, or an engineer six months later, reads the Context + Decision prose to understand *why* redis, not postgres.
- **Greppable** — each entry's header carries `blast:<radius>` and `rev:<reversibility>` slugs, so an automated pass (or a future gate) can flag every `blast:data` / `rev:effectively-irreversible` choice without parsing prose.

One file, one form. PLAN.md §1 is a one-line pointer to it — decisions are not duplicated in PLAN.md.

## When to invoke

Use `decide` when ANY of these are true:

| Trigger | Decision worth recording? |
|---|---|
| You're planning a non-trivial decision in `/arh-plan-implementation` Phase 1 | yes — one entry |
| You promote a decision to a full ADR in `docs/adr/` | yes — set the `adr:` slug to the ADR id |
| Mid-implementation: agent picks library variant / DB engine / sync-vs-async at a non-trivial boundary | yes — even if it wasn't in PLAN, the choice is visible in the diff |
| Rename a helper / pick a variable name / inline a one-line util | no |

Rule of thumb: **if a competent reviewer might pick a different option from the same prompt, record it.** If three readers would all reach the same conclusion, skip.

## Entry format

Append to `docs/features/<id>/DECISIONS.md`. If the file does not exist, create it with the title `# <id> — Decisions` and a one-line intro, then the first entry.

```
### D-NN: <one-line title> · blast:<feature|service|system|data> · rev:<mechanical|medium|effectively-irreversible> · adr:<ADR-NNNN|—>

**Context**: <one paragraph; the constraint that ruled other options out>

**Decision**: <one paragraph; the choice + specifics>
```

### Field guidance

**`D-NN`** — zero-padded, sequenced within the feature (first is `D-01`). NOT global.

**title** — one line, the choice in plain words. This is what the pointer and reviews cite.

**`blast:`** — pick the smallest accurate value:
- `feature` — wrong choice only hurts this feature. Inline retries vs library retries.
- `service` — affects this whole service. Async dispatch vs sync at boundary.
- `system` — affects ≥2 services. New external dep. Schema change shared across services.
- `data` — touches durable state. Schema migration, encoding choice, retention default. Highest scrutiny.

**`rev:`** — pick the most pessimistic accurate value:
- `mechanical` — swap the lib, rewrite a file. Hours.
- `medium` — re-migration, deprecation window, careful rollout. Days–weeks.
- `effectively-irreversible` — data migrated under the choice; rolling back means data loss or incompatible migrations. Months and high risk.

**`adr:`** — the full-ADR id (`ADR-0017`) if this decision was promoted to `docs/adr/`. Otherwise `—`.

**Context** — one paragraph: the constraint that makes this a decision, not a default. If there is no constraint, it isn't decision-log-worthy — drop it.

**Decision** — one paragraph: the choice and its specifics (the concrete lib/engine/pattern and any parameters).

### When a decision must be promoted to a full ADR

"Outlives this story" is not a judgment call — the `blast:` / `rev:` slugs decide it mechanically:

> Promote to a full ADR under `docs/adr/` (set `adr:ADR-NNNN`, not `—`) when **either**:
> - `blast:` is `system` or `data` — the choice reaches beyond this one feature (a new external dependency, a cross-service change, or anything touching durable state), **or**
> - `rev:` is `effectively-irreversible` — undoing it means data loss or an incompatible migration.
>
> A `feature` / `service` choice that is `mechanical` / `medium` to reverse stays story-local — DECISIONS.md only, `adr:—`.

This is the machine meaning of "outlives this story", and it is the single source of truth — `plan-authoring` and `impl-planning-agent` defer to it. `plan-validation` enforces it: a `blast:{system,data}` or `rev:effectively-irreversible` entry left at `adr:—` fails the plan. Promote via `adr-template`, then set the `adr:` slug on the entry.

## Procedure

1. Confirm the decision passes the "competent reviewer might disagree" bar. If not, stop — no entry.
2. Read `docs/features/<id>/DECISIONS.md`. If absent, create it with the title + intro. (If the per-feature record `docs/features/<id>/state.json` is also absent, this skill is being invoked out of order — `/arh-plan-implementation` Phase 1 must run after `/arh-plan-requirements`.)
3. Compute the next `D-NN` from the existing entries (default `D-01`).
4. Append the entry above. Keep `Context` and `Decision` to one paragraph each.
5. If a full ADR was authored under `docs/adr/`, set the `adr:` slug accordingly. Otherwise `—`.

## Anti-patterns

- **Don't** duplicate the entry into PLAN.md §1 — §1 is a pointer to this file.
- **Don't** mutate an existing entry to "update the rationale". Append a new entry that supersedes the old; the audit trail matters more than tidiness.
- **Don't** record trivial choices. Name picking, internal helper boundaries, code-style preferences — these are not decisions in this sense.
- **Don't** omit `blast:` / `rev:` — the greppable slugs are the machine half of the record.

## Read-only consumers

- `/arh-implement` context-load — reads each entry so the implementer honors the recorded choices.
- `/arh-review` code review (`review-assessment` `adr-violation` dimension) — flags a diff that contradicts a logged decision or a promoted full ADR.
- `/arh-implement` commit-PR — lists the decisions honored in the PR body.
- The playbook site — surfaces `DECISIONS.md` as a per-feature page.
