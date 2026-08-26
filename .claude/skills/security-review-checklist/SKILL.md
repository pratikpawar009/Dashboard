---
name: security-review-checklist
description: OWASP Top 10 / CWE-driven review checklist organised by category (input, authn/authz, data, crypto, deps, logs, errors). Used by security-review-agent.
when_to_use: Security-gating a PR or feature branch during /arh-security-review.
user-invocable: false
allowed-tools: Read Grep Glob
---
# Security Review Checklist

> **Precedence.** The invariants behind these checks are canonical in the
> `security-baseline` rule (`rules/security-baseline.md`) — this file is the
> review-time checkbox form plus the SAST regex table. If wording ever differs,
> the rule wins; fix the drift here, not there.

## Input

- [ ] All untrusted input validated at trust boundaries.
- [ ] No string-built SQL, no `eval`, no shell-string concatenation.
- [ ] File uploads checked for type, size, and path traversal.

## Authentication and authorization

- [ ] Every protected endpoint enforces authn AND authz.
- [ ] Tokens scoped (least privilege) and rotated.
- [ ] Sessions invalidated on logout and password change.

## Data

- [ ] No PII in logs.
- [ ] Sensitive fields encrypted at rest with documented key management.
- [ ] Backups exclude secrets or use sealed encryption.

## Crypto

- [ ] No homegrown crypto.
- [ ] Modern primitives only (no MD5/SHA1 for security; no DES; no ECB).

## Dependencies

- [ ] No new high/critical CVEs in `npm audit` / `pip-audit` / equivalent.
- [ ] License compatibility verified.

## Logs and errors

- [ ] User-facing errors leak no internal state, stack traces, or identifiers.
- [ ] Audit-relevant events logged with actor, action, target, outcome.

## Detectable patterns (SAST grep — run before manual checklist)

The security-review-agent grep-scans the diff for each pattern below. A hit auto-classifies as the listed severity unless the agent verifies a safe context. Negative-rule: a comment justifying the usage (`// SECURITY-OK: <reason>`) downgrades to Medium for review-by-human.

### Input — Critical / High

| Pattern (regex, case-insensitive) | Languages | Category | Default severity |
|---|---|---|---|
| `\beval\s*\(` | JS/TS/Python | Arbitrary code execution | Critical |
| `\bnew\s+Function\s*\(` | JS/TS | Arbitrary code execution | Critical |
| `\bexec\s*\(` (Python) | Python | Arbitrary code execution | Critical |
| `subprocess\.(call|run|Popen)\([^)]*shell\s*=\s*True` | Python | Command injection | Critical |
| `child_process\.exec\b` | JS/TS | Command injection | High |
| `os\.system\s*\(` | Python | Command injection | High |
| String concat in SQL: `"SELECT .*"\s*\+\s*\w+` or f-string `f"SELECT.*\{` | Any | SQL injection | Critical |
| `dangerouslySetInnerHTML` | React | XSS sink | High |
| `innerHTML\s*=` | JS/TS | XSS sink | High |
| `document\.write\s*\(` | JS/TS | XSS sink | High |

### Auth / crypto — Critical / High

| Pattern | Languages | Category | Default severity |
|---|---|---|---|
| `algorithm\s*[:=]\s*["']?none["']?` (JWT) | Any | JWT `none` algorithm | Critical |
| `rejectUnauthorized\s*:\s*false` | Node TLS | TLS verify disabled | Critical |
| `verify\s*=\s*False` (requests) | Python | TLS verify disabled | Critical |
| `\bMD5\b|\bSHA1\b` used for password/token hashing | Any | Weak hash | High |
| `DES\b|ECB\b` | Any | Weak cipher mode | High |
| Hardcoded secret: `(api[_-]?key|password|secret|token)\s*[:=]\s*["'][A-Za-z0-9+/=_-]{16,}["']` | Any | Embedded credential | Critical |

### Data — High

| Pattern | Languages | Category | Default severity |
|---|---|---|---|
| `console\.log\([^)]*\b(email|password|token|ssn|phone)\b` | JS/TS | PII in logs | High |
| `print\([^)]*\b(email|password|token|ssn|phone)\b` | Python | PII in logs | High |
| `log\.\w+\([^)]*\$\{?\s*(token|password|secret)` | Any | Secret in logs | Critical |

### Procedure

The agent runs `git diff main...HEAD -U0 -- <source-dirs>` then greps each pattern against the diff. For every hit it records:

```
file:line | pattern matched | severity | suggested fix
```

The findings flow into the consolidated security report alongside the manual checklist results.

## Anti-pattern

- Suppress hits with blanket `// eslint-disable-next-line` / `# noqa: S*` without a comment — agent demands `// SECURITY-OK: <reason>` form or escalates.
- Reclassify Critical hits to Medium without an ADR — Critical/High → blocking by design.
