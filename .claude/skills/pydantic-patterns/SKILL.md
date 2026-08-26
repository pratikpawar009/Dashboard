---
name: pydantic-patterns
description: pydantic patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing pydantic code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# pydantic Patterns

<!-- Harness scaffold: stack=pydantic — STRUCTURE only; -->
<!-- Fill every CORE section below. Under OPTIONAL, keep only the sections that apply to -->
<!-- this stack and DELETE the heading+slot of the rest BEFORE filling. Keep ≤ 200 lines. -->
<!-- Deletion is safe: OPTIONAL slots use the word OPTIONAL (not TODO) so the lint does not -->
<!-- nag for them; CORE TODO slots are nagged until filled — that is intentional. -->
<!-- Loaded by implementation-, impl-planning-, validation-, code-review-, security-review-, -->
<!-- scaffold-, and cicd-agents when this stack is active. -->

## Verified facts

<!-- BEGIN VERIFIED FACTS -->
<!-- Owned by skill `deep-scan-verification` (/arh-init Phase 6) — `harness fill` never -->
<!-- edits between these markers. Empty until a brownfield deep scan approves facts here. -->
<!-- Each bullet ends in (see file:line); the file it cites is this fact's proof. -->
<!-- END VERIFIED FACTS -->

## Idioms

- All request/response schemas subclass `pydantic.BaseModel` directly (`app/schemas/activity.py`) — no shared project base class exists yet.
- `Field(..., description=...)` is used for documentation metadata on required fields (`app/schemas/activity.py:9`); optional/plain fields use bare type annotations.
- Timestamps are typed `datetime` and left to Pydantic v2's built-in coercion — no hand-rolled date parsing (`app/schemas/activity.py:11,19-20`).
- IDs are typed `str` (not `int`, not a custom `UUID` field) — the API layer stringifies a `uuid.uuid4()` before constructing the response model (`app/api/ingest.py:21`, `app/schemas/activity.py:16`).
- Runtime config is a *separate* pattern from request/response schemas: `Settings(BaseSettings)` with `SettingsConfigDict(env_file=".env", extra="ignore")` (`app/core/config.py:4-7`) — do not mix env-sourced config fields into request/response models.
- No `@field_validator`/`@model_validator` usage exists in the scaffold yet — undecided; when validation logic is needed, use Pydantic v2's validator decorators rather than validating in the route body.

## Project structure

- `app/schemas/<domain>.py` — one module per domain concept, holding both the inbound and outbound models side by side (`app/schemas/activity.py` has `ActivityEventIn` and `ActivityEventOut`).
- `app/core/config.py` — the single `Settings`/`settings` instance for env-sourced runtime config, separate from `app/schemas/`.

## Layering & dependency rules

- `app/schemas/*` modules have no dependency on `app/api/*` or `app/core/*` — they are pure leaf modules importable from any layer.
- `app/core/config.py`'s `Settings` is not imported by `app/schemas/*` and vice versa — config and DTO schemas stay separate concerns even though both use Pydantic.

## Error handling

- Pydantic's own `ValidationError` on a request model is caught by FastAPI before the route body runs, and handed to the `RequestValidationError` handler in `app/core/errors.py:21-26` (HTTP 422, `code: "validation_error"`, `details: exc.errors()`).
- Schemas do not define their own error handling — they rely on fastapi-patterns' registered exception handler for the response shape.

## Anti-patterns

- Reusing one model for both request and response when their fields differ — `ActivityEventIn` requires `payload` and has no `id`/`received_at`; `ActivityEventOut` is the mirror without `payload` (`app/schemas/activity.py:6-20`). Follow that in/out split, don't collapse it.
- Putting env/secret access inside a request or response schema — that belongs only in `Settings` (`app/core/config.py`).
- Hand-validating something Pydantic already does via typed fields (e.g. manual `datetime.strptime` on a string field instead of a `datetime`-typed field).

## Examples

BAD — one model doing double duty for request and response:
```python
class ActivityEvent(BaseModel):
    id: str | None = None       # only set on the way out
    source: str
    payload: dict | None = None  # only set on the way in
```

GOOD — separate in/out models (app/schemas/activity.py:6-20):
```python
class ActivityEventIn(BaseModel):
    source: str = Field(..., description="Producer id")
    event_type: str
    occurred_at: datetime
    payload: dict

class ActivityEventOut(BaseModel):
    id: str
    source: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
```

## References

- `services/api/app/schemas/activity.py` — in/out model split
- `services/api/app/core/config.py` — pydantic-settings usage
- `services/api/app/core/errors.py:21-26` — validation error handler
- `docs/adr/0002-system-architecture.md` — Interfaces & contracts

## Security (stack-specific)

Request models are the trust-boundary validation control required by `.claude/rules/security-baseline.md` ("Validate untrusted input at trust boundaries"): every inbound field on `ActivityEventIn` is typed and required or explicitly defaulted (`app/schemas/activity.py:6-12`), so malformed ingest payloads fail at the model boundary (422) before reaching handler code. No `model_config` currently sets `extra="forbid"` on request schemas — unexpected extra fields are silently accepted (default Pydantic v2 behavior), which is worth revisiting if stricter input rejection is needed.

## Logging, config & observability

Runtime config is the one place pydantic is used outside request/response schemas: `Settings(BaseSettings)` reads from `.env` with `extra="ignore"` (`app/core/config.py:4-15`) — env vars not declared on `Settings` are silently dropped rather than erroring. `LOG_LEVEL`, `DATABASE_URL`, `APP_NAME`, `ENVIRONMENT` are the only declared fields today (`.env.example:1-4`). New config values must be added as typed fields on `Settings`, not read via `os.environ` elsewhere.
