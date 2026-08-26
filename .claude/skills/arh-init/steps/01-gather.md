# Phase 1 — Gather info

Goal: ask the user for the 10 pieces of context the harness needs but cannot derive. Block on missing required items; auto-fill when detection answered.

## Required questions

| # | Question                                            | Auto-fill source            | Block if missing |
|---|-----------------------------------------------------|------------------------------|------------------|
| 1 | Product type (web, mobile, backend, cli, library)   | none — always asked          | yes              |
| 2 | Primary languages                                   | manifest files               | yes              |
| 3 | Target environments (web/mobile platforms, OS)      | none                         | yes              |
| 4 | Domain / business context (1–3 sentences)           | `$ARGUMENTS`, or `harness.yaml project.description` | yes |
| 5 | Personas (3–5 named user roles)                     | none                         | yes              |
| 6 | External integrations (Jira/Linear/Figma/etc.)      | `harness.yaml integrations`   | no               |
| 7 | Safety / compliance constraints (PII, HIPAA, etc.)  | `harness.yaml governance`     | no               |
| 8 | Test framework                                       | manifest files               | yes              |
| 9 | Design system / Figma file key                      | none                         | no — only when role is frontend or mobile |
| 10 | Conventions — project-wide always-do-X rules        | none                         | no              |

Question 10 wording: *"Any project-wide always-do-X rules? Bullet list, ≤8 items, each ≤120 chars. Examples: 'Never push directly to main', 'Run lint pre-commit', 'All API mutations require user_id scope', 'State writes use status literals only — tracker keys live in tracker_* fields'."* Cap at 8 bullets per Anthropic CLAUDE.md specificity guidance.

## Behaviour

- For each required item without a source, ask the user one question at a time. Do not advance until answered.
- For optional items, default to a sensible value and note the default in the answer log.
- Persist answers to a temporary markdown table; Phase 4 (`bootstrap-agent`) reads from it.

## Feeds Phase 4

The Conventions, Personas, Domain, and Target-platforms answers are consumed by `bootstrap-agent` in Phase 4b to fill the project memory file. Collect these completely and unambiguously here — anything missing will be left as a TODO.

## Memory-file overwrite pre-approval (re-run case)

`/arh-init` is idempotent. On a re-run, the project memory file may already have content in the `Conventions` / `Personas` / `Domain glossary` / `Target platforms` sections. Resolve overwrites here so Phase 4b can apply them directly:

- If any of those sections already has non-TODO content, show the user the existing content and ask whether to overwrite (one section at a time).
- Record each decision in the answer log as `overwrite:<section>=yes|no`. Phase 4b reads these flags: it overwrites only pre-approved sections, leaves the rest untouched, and reports every overwrite it performs.

## Anti-pattern

- Don't ask everything in one big prompt — small atomic questions get higher-quality answers.
- Don't skip required items because the user is in a hurry. Surface why each one matters.
