---
name: security-assessment
description: Run a security review — dependency scan, SAST grep, OWASP checklist + compliance overlay, stack-pattern check, consolidated report + verdict + state write. Used by security-review-agent.
user-invocable: false
---
# Security assessment

The method for gating a feature on security defects. Apply these passes in order; all
findings stream into one shared list that the report consolidates. Use skill
`security-review-checklist` for the OWASP categories + Detectable-patterns (SAST) set.

## Inputs

- `docs/features/$ARGUMENTS/PLAN.md` — file-list scope.
- `docs/features/$ARGUMENTS/DATA-DESIGN.md` (when present) — PII/sensitive field classification, encryption-at-rest, retention/deletion, and the ownership/tenancy scoping the diff must enforce. High-signal for the active governance profile.
- `docs/features/$ARGUMENTS/REQUIREMENTS.md` — NFR-security budgets, PII-handling claims.
- `docs/features/$ARGUMENTS/REVIEW.md` (if present) — avoid double-flagging architecture findings.
- `CLAUDE.md` — stack list, target platforms, compliance constraints.
- `.claude/rules/*.md` — rules matching changed-file globs, incl. `governance/<profile>/` when a non-default profile is active.
- Governance profile: read `harness.yaml governance.profile`. It holds **either a single name or a list** — a config written before profiles became stackable, or by hand, may still be the bare string `standard`. Read it as a list of one when it is a string, and treat `standard` as present whether or not it is written down; the composer always loads it. Record any other active compliance overlay (`hipaa`/`pci`/`sox`/`gdpr`) and apply its rules.

## Dependency vulnerability scan

Run if the diff touches a dependency manifest (`package.json`/lockfiles, `pyproject.toml`/`poetry.lock`/`uv.lock`/`requirements.txt`, `Gemfile.lock`, `go.sum`, `pom.xml`/`build.gradle`/`build.gradle.kts`, `Cargo.lock`, `composer.lock`). Otherwise skip with `Dependency scan: skipped — no manifest changes.`

Pick the audit tool from `docs/adr/0001-tech-stack.md` § Decision (Frameworks list). If the ADR is missing, run `/arh-init` first:

| Stack | Tool | Command |
|---|---|---|
| `nextjs` / `react` / `react-native` / `express` (pnpm) | `pnpm audit` | `pnpm audit --json` |
| `nextjs` / `react` / `react-native` / `express` (npm) | `npm audit` | `npm audit --json` |
| `nextjs` / `react` / `react-native` / `express` (yarn) | `yarn audit` | `yarn audit --json` |
| `fastapi` / `django` (uv / poetry) | `pip-audit` | `pip-audit --format json` |
| `spring` (maven) | `dependency-check` | `mvn org.owasp:dependency-check-maven:check -DfailBuildOnCVSS=7` |
| `spring` (gradle) | `dependency-check` | `gradle dependencyCheckAnalyze` |
| `ruby on rails` | `bundler-audit` | `bundle audit check --update` |
| `go` | `govulncheck` | `govulncheck ./...` |
| `cargo` / `rust` | `cargo-audit` | `cargo audit --json` |
| `terraform` | `tfsec` | `tfsec --format json .` |
| `k8s` | `kubesec` | `kubesec scan <manifest>` |

Tool not on `PATH` → record a `tool_missing` finding at Low (NOT a blocker; CI is expected to install it). Severity map: `critical`/CVSS≥9.0 → Critical; `high`/7.0–8.9 → High; `moderate`/4.0–6.9 → Medium; `low`/<4.0 → Low; `info` omitted.

```
finding:
  source:    "deps-scan/<tool>"
  severity:  Critical | High | Medium | Low
  package:   "<name>@<version>"
  advisory:  "GHSA-xxxx-xxxx-xxxx" | "CVE-202X-XXXXX"
  fixed_in:  "<version>" (or "no fix available")
  paths:     ["dependencies > foo > bar"]
  fix:       "Upgrade to <version>" | "Pin transitive dep" | "Vendor patch"
```

Do NOT auto-bump versions here — only report (bumps belong in the fix loop). Do NOT mask transitive vulns without a `// SECURITY-OK: <reason>` comment.

## SAST grep pass

1. `git diff main...HEAD -U0 -- '<source-globs-from-PLAN>'` — added/changed lines only.
2. For every pattern row in `security-review-checklist` `## Detectable patterns`, run the regex against the diff.
3. For every hit: extract file, line, matched text; look 3 lines above (or end-of-line) for a `// SECURITY-OK: <reason>` / `# SECURITY-OK: <reason>` comment. Present with a non-empty reason → downgrade to Medium and append the reason. Otherwise emit at the pattern's default severity.

```
finding:
  source:    "sast/<pattern-id>"
  severity:  Critical | High | Medium | Low
  category:  "input | auth | crypto | data | logs"
  file:      "src/auth/login.ts"
  line:      42
  matched:   "<excerpt>"
  pattern:   "<regex>"
  fix:       "<one-line suggestion>"
  override:  "<reason from // SECURITY-OK comment, if any>"
```

Override rules: comment on the line above or end-of-line; reason must be non-empty (bare `// SECURITY-OK` → Critical); applies to ONE match only. Ignore wide-scope suppressors (`// eslint-disable file`) — grep anyway. `// SECURITY-OK: bypass` rejected; the reason must explain WHY.

## Manual OWASP checklist + compliance overlay

Apply the six checklist categories from `security-review-checklist` (Input / Authentication and authorization / Data / Crypto / Dependencies / Logs and errors) to the diff — the per-category check contents are canonical in that skill; do not re-derive them here. Only flag where the diff introduces or modifies risk surface, never as a tick-box on untouched items. (Dependencies are largely covered by the deps scan above.)

**Compliance overlay** — when `profile` is `hipaa` (PHI handling, audit logging, breach notification) / `pci` (cardholder isolation, tokenisation, quarterly scan) / `sox` (change control, segregation, audit trail) / `gdpr` (data-subject rights, consent, cross-border), additionally apply `.claude/rules/governance/<profile>/`. Findings tagged with a compliance domain (e.g. `compliance: hipaa.phi-handling`) appear in both the main list AND the report's `## Compliance impact` section. Never apply a profile the project did not activate.

**Stack-pattern pass** — for every `<framework>-patterns` skill loaded, scan for stack-specific idioms. Examples:

| Stack | Idioms |
|---|---|
| `nextjs` | Server-action input validation (zod), no `unsafe-inline` in CSP, secrets never in client components |
| `fastapi` | `Depends()`-based auth, `response_model` strips sensitive fields, OAuth2 scopes |
| `django` | CSRF middleware enabled, no raw SQL via `connection.cursor` without params |
| `react-native` | No PII in AsyncStorage without encryption, deep-link validation |
| `terraform` | No `0.0.0.0/0` ingress unless explicitly bastion, S3 buckets versioning + encryption |

Empty body → generic fallback (G15 warning printed at the gate).

```
finding:
  source:     "checklist/<category>" | "compliance/<profile>.<rule>" | "stack-pattern/<framework>"
  severity:   Critical | High | Medium | Low
  category:   input | auth | crypto | data | logs | compliance | stack
  file:       "<path>"
  line:       <int>
  issue:      "<one-line description>"
  fix:        "<one-line suggestion>"
  rule_id:    "<rule-or-checklist-id>"
```

## Consolidated report + verdict

Write one report at `docs/features/$ARGUMENTS/SECURITY-<YYYYMMDD-HHMM>.md`:

```
# Security review — $ARGUMENTS

- Date: <iso8601>
- Verdict: PASS | BLOCKED
- Governance profile: <profile>
- Compliance overlays applied: <list or "none">
- Total findings: <T>  (Critical: <C>, High: <H>, Medium: <M>, Low: <L>)
- Duration: <total seconds>

## Summary

| Source         | Critical | High | Medium | Low |
|----------------|----------|------|--------|-----|
| SAST (grep)    |    0     |  1   |   2    |  0  |
| Deps scan      |    1     |  0   |   0    |  3  |
| OWASP checklist|    0     |  2   |   1    |  0  |
| Stack patterns |    0     |  0   |   1    |  0  |
| Compliance     |    0     |  1   |   0    |  0  |

## Critical findings

### F-001 — Embedded credential in src/api/auth.ts:42

- Source: sast/hardcoded-secret
- Severity: Critical
- Matched: `const API_KEY = "sk-prod-abc123..."`
- Fix: move to env var, use `process.env.API_KEY` with fail-fast on absence
- Override: none

### F-002 — CVE-2024-XXXXX in `lodash@4.17.20`

- Source: deps-scan/pnpm
- Severity: Critical
- Path: dependencies > lodash
- Fix: upgrade to lodash@4.17.21

## High findings
...
## Medium findings
...
## Low findings
...

## Compliance impact
(only when governance.profile includes anything besides "standard")
| Finding | Compliance domain | Profile rule |
|---------|-------------------|--------------|

## Tool-missing report
- <tool> (<stack>): not on PATH. Install in CI before merge.

## Action plan
1. Fix Critical findings before merge (blocking).
2. Fix High findings before merge (blocking).
3. Address Medium within 1 sprint OR justify with ADR.
4. Track Low in backlog.
```

| Verdict | Condition |
|---|---|
| `PASS`    | 0 Critical AND 0 High AND no compliance-tagged carry-forward pending |
| `BLOCKED` | ≥1 Critical OR ≥1 High OR ≥1 compliance-tagged item in `pending_carry_forward` |

Tool-missing (Low) does not flip to BLOCKED. Stack-pattern + compliance findings count toward the total per their severity. Never reclassify severity to force PASS — the SAST patterns + deps-scan maps are the source of truth.

**Carry-forward enforcement (RC3).** Read `docs/features/$ARGUMENTS/state.json` at `.pending_carry_forward`. For every entry where `kind == "finding"` AND its tags/category match the active profile (profile=hipaa → `hipaa`/`phi`/`audit-logging` tags), force verdict `BLOCKED` regardless of counts — compliance-tagged carry-forward cannot be merged with `--accept-pending`. List them under a `## Compliance carry-forward blocking merge` section with the `harness carry-forward resolve <id> --evidence <path>` remedy.

### State write (mandatory, unconditional)

After writing the report, update state per `docs/state/SCHEMA.md § Writer rule` for `$ARGUMENTS`. `security` + `phase` are B-tier (write PRIMARY `docs/features/$ARGUMENTS/state.json` AND MIRROR `docs/state/features.json[$ARGUMENTS]`); `security_findings` + `security_report` are P-tier. Runs regardless of issue-tracker provider.

```json
{
  "security":          "PASS | BLOCKED",
  "security_findings": {
    "critical": <int>, "high": <int>, "medium": <int>, "low": <int>,
    "tool_missing": ["<tool-name>", ...]
  },
  "security_report":   "docs/features/$ARGUMENTS/SECURITY-<DATE>.md",
  "phase":             "security-reviewed",
  "last_updated":      "<iso8601>"
}
```

Status fields (`security`, `phase`) MUST be literals — see `docs/state/SCHEMA.md § Field ownership`. `security_report` is a data field, not status. Writing the report without the state write loses the verdict signal for downstream phases.
