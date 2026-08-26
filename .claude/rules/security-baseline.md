---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.go"
  - "**/*.rs"
  - "**/*.java"
  - "**/*.kt"
---
# Security baseline

Canonical source for cross-cutting security invariants. PRDs reference this file via `Per `.claude/rules/security-baseline.md`:` instead of inlining the bullets below.

## Core

- Never log tokens, passwords, API keys, session ids, or PII (email, name, address, phone, IP, raw user-supplied content like URLs, titles, descriptions, file content) at any log level. Log opaque identifiers (`user_id`, `resource_id`) only.
- Validate untrusted input at trust boundaries (HTTP handlers, message consumers, CLI argv). Re-validate at the service layer as defence-in-depth.
- No `eval`, no string-built SQL. Use parameterised queries / prepared statements / ORM with bind variables.
- Treat environment variables as untrusted unless the deploy contract documents otherwise.
- Errors shown to end users contain no stack traces or internal identifiers.
- Secrets live in env vars or the project's secret store; never committed to git.

## Ownership and authorization

- Every per-resource mutation (PATCH, PUT, DELETE, bulk variants) enforces ownership at the service layer via a `_load_owned(id, user_id) -> Resource | None` style helper. The helper executes a single `SELECT ... WHERE id = :id AND user_id = :user_id`; zero rows → HTTP 404.
- **Return HTTP 404, never 403**, for foreign-owned or non-existent resource ids. 403 confirms existence (OWASP IDOR / enumeration leak).
- The ownership check runs BEFORE any field read or mutation. Test fixtures MUST capture the SQL trace and assert SELECT-before-UPDATE on foreign ids.
- Authenticated routes that omit a user-context check are forbidden.

## Auth tokens, SSRF, parsing, rate-limit, CSRF (one-line invariants)

- **Auth tokens**: CSPRNG ≥ 32 bytes; single-use enforced at DB level; magic-link TTL ≤ 15 min; session cookie ≤ 30 days w/ `Secure` + `HttpOnly` + `SameSite=Lax|Strict`; passwords stored via argon2id/bcrypt + per-deploy pepper.
- **SSRF**: validate URLs AFTER DNS resolution; block RFC1918 + loopback + link-local + ULA; re-validate after every redirect (≤ 5 hops); outbound fetch hard timeout ≤ 5 s + byte cap ≤ 2 MB; identifying `User-Agent`.
- **Parsing safety**: HTML/XML parsers in safe mode (XXE disabled, no JS exec); uploads MIME-sniff + extension match before process; size caps at HTTP layer (413); bounded-reader pattern.
- **Rate limit**: auth endpoints throttled per (hashed) email AND IP, default 3/email/60min rolling; HTTP 429 + `Retry-After`; never reveal whether the email exists.
- **CSRF**: same-site cookie + CSRF token header for state-changing ops on browser surfaces; PATCH/PUT/POST/DELETE require the header; GETs exempt.

## BAD

```python
log.info(f"User {user.email} logged in with token {token}")
```

```python
# Foreign owner returns 403 → existence leak
if resource.user_id != current_user.id:
    raise HTTPException(403, "forbidden")
```

## GOOD

```python
log.info("User logged in", extra={"user_id": user.id})
```

```python
def _load_owned(session, resource_id: int, user_id: int) -> Resource | None:
    return session.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.user_id == user_id,
        )
    ).scalar_one_or_none()

# Router
row = _load_owned(session, resource_id, current_user.id)
if row is None:
    raise HTTPException(404, "not_found")
```

## How PRDs reference this rule

`- Security: Per `.claude/rules/security-baseline.md`: applies to <scope>. <feature-specific only>`

Do NOT re-paste bullets in PRDs; the rule body is canonical.
