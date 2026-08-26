# dashboard

dashboard harness AI sdlc monitoring dashboard 

@README.md
@docs/config/project-commands.yaml

## Tech stack

- **fastapi**
- **typescript**
- **next**
- **postgres**
- **pytest**
- **alembic**
- **pydantic**


## Integrations

- Document tracker: `local`
- Issue tracker: `github`
- VCS: `github`
- CI: `none`

## SDLC

State machine: `docs/state/features.json` (index, pre-plan) + `docs/features/<id>/state.json` (per-feature, post-plan). See `docs/state/SCHEMA.md` for the two-tier shape. Gated by `phase-preconditions` skill.

Greenfield: `/arh-init` → `/arh-scaffold` → `/arh-intake` → `/arh-validate-story` → `/arh-research` → `/arh-plan-requirements` → `/arh-plan-implementation` → `/arh-implement` → `/arh-validate-feature` → `/arh-review` → `/arh-security-review`.

Brownfield: `/arh-init` → `/arh-import --jira-jql "..."` → continue per feature.

Helpers: `/arh-trace`, `/arh-explain <id>`, `/arh-sync`, `harness carry-forward {list|resolve|defer}`.

## Where to look

| What | Where |
|---|---|
| Build / test / dev commands | `docs/config/project-commands.yaml` (auto-imported above) |
| Stack idioms + anti-patterns + design tokens | `.claude/skills/<framework>-patterns/SKILL.md` (one per declared stack) |
| Cross-cutting rules (security, a11y, perf, reusability) | `.claude/rules/*-baseline.md` (auto-loaded, path-scoped) |
| Architectural decisions | `docs/adr/<NNNN>-<slug>.md` |
| Per-feature artefacts (story → research → PRD → PLAN → review) | `docs/features/<id>/` |
| Tracker config | `docs/config/{issue-tracking,doc-tracker}.yaml` |

<!-- Harness scaffold — sections below filled by /arh-init Phase 4 (bootstrap-agent) -->

## Conventions

- Never push directly to main.
- Run lint + tests before every commit.

## Personas

- Engineering Manager — team-level delivery health, bottlenecks, feature velocity across the SDLC.
- Individual Contributor / Developer — day-to-day view of their own features, review/validation status.
- Executive / Leadership Stakeholder — high-level rollups: progress, risk, governance posture.
- Project Manager — cross-feature timelines, blockers, tracker sync status.
- Architect — architecture decisions, cross-cutting risk, stack/ADR drift.
- QA — validation/review outcomes, test evidence, security-review status.

## Domain glossary

- Harness — the AI-SDLC framework this dashboard monitors (state machine, skills, ADRs, per-feature artefacts).
- SDLC activity — AI-assisted development lifecycle events (intake, plan, implement, review) ingested from `.github/hooks/` and the agentrise MCP.
- Governance artifact — a produced compliance/process record (ADR, review, validation report) whose counts feed the dashboard.

## Target platforms

Web (desktop + mobile responsive) — no native/desktop app target.

## Branch conventions

`feature/<id>`, `bugfix/<id>`, `hotfix/<id>`, `chore/<id>`.

## Commit format

Conventional Commits: `type(scope): summary`.

## PR conventions

Title: `type(scope): summary`. Body sections: Summary, Test plan, Migration (if applicable). Never push directly to main — always via PR.

## Design system

No Figma/formal design system. Reference: html-mockup pages at `docs/design/` (fileKey/url TODO — see `docs/design/schema.json`; pages not yet created).
