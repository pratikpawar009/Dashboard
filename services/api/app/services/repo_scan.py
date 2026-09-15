"""ING-07 -- GitHub org repo-scan service.

Sole importer of `httpx` for GitHub calls per D-03 (dedicated per-feature
seam, deliberately NOT merged with `app/auth/jwks.py`'s JWKS client -- different
auth model, different retry semantics). Two operations:

- `_list_org_repos` -- `GET /orgs/{org}/repos?per_page=100`, paginated via
  the `Link: rel="next"` header until exhausted.
- `_probe_program_yaml` -- `GET /repos/{org}/{repo}/contents/.harness/program.yaml
  ?ref={default_branch}`; 200 = installed, 404 = not installed. Presence-only
  signal per Story Clarifications 2026-09-15 -- the response body is NOT
  parsed.

Retries via `app.core.retry.retry_with_backoff` per D-04 on 429 / 5xx /
timeout, `max_attempts=4` (1 initial + 3 retries per FR-3). Per-call timeout
is `httpx.Timeout(10.0)`. Non-retryable 4xx (401/403/...) fails fast. On
retry exhaustion or any unrecoverable upstream state, raises `GitHubScanError`
so the router (T-04) aborts before committing the rollup upsert (FR-4
no-partial-write).

Logging discipline (NFR-security, TC-17): the PAT, the `Authorization` header
value, and raw upstream response bodies are NEVER logged. Every log record
uses the field allowlist `{repo, org, status_code, attempt, duration_ms,
error_kind}`; exception messages are collapsed to a categorical `error_kind`
label rather than propagated as-is, so a mis-echoed upstream body containing
a secret cannot leak through `str(exc)`.

The service performs the rollup upsert on the passed `AsyncSession` but does
NOT commit -- the request-scoped router (T-04) owns the transaction boundary
so a mid-scan `GitHubScanError` auto-rolls back the whole request.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Final

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.retry import retry_with_backoff
from app.models.rollup import OrgSummaryRollup
from app.schemas.repo_scan import ScanReposResponse

logger = logging.getLogger(__name__)

_GITHUB_API_BASE: Final[str] = "https://api.github.com"
_PROBE_PATH: Final[str] = ".harness/program.yaml"
_PAGE_SIZE: Final[int] = 100
_ORG_ID: Final[str] = "org-1"
_HTTP_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(10.0)
# FR-3: <=3 retries after the first attempt -> 4 total. TC-09 asserts exactly 4.
_RETRY_MAX_ATTEMPTS: Final[int] = 4


class GitHubScanError(Exception):
    """Raised when GitHub interaction fails after the bounded retry budget.

    The router (T-04) maps this to HTTP 502 (FR-3 / FR-4). Carries only a
    categorical `error_kind` label -- never an upstream response body,
    request URL, or `str(underlying_exc)` -- so a mis-echoed PAT / raw
    payload cannot leak through the exception chain (TC-17).
    """

    def __init__(self, error_kind: str) -> None:
        super().__init__(error_kind)
        self.error_kind = error_kind


class _RetryableStatus(Exception):
    """Internal signal that the last HTTP response is retryable (429 / 5xx).

    Kept module-private so `retry_with_backoff`'s bare `except Exception`
    path retries on it while the retryable-vs-fatal distinction stays inside
    this module.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"retryable_status:{status_code}")
        self.status_code = status_code
        self.error_kind = "rate_limited" if status_code == 429 else "upstream_5xx"


def _classify_error_kind(exc: BaseException) -> str:
    """Categorical label for log / raise sites -- never `str(exc)` (TC-17)."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, _RetryableStatus):
        return exc.error_kind
    return "http_error"


def _next_page_url(link_header: str | None) -> str | None:
    """Return the `rel="next"` URL from a GitHub `Link` header, or `None`.

    GitHub emits `Link: <url1>; rel="next", <url2>; rel="last"`. We ignore
    every rel other than `next`. Malformed segments are skipped silently --
    exhausting pagination is the same outcome as never having a `next` link.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        segments = part.strip().split(";")
        if len(segments) < 2:
            continue
        url_part = segments[0].strip()
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        for meta in segments[1:]:
            if meta.strip() == 'rel="next"':
                return url_part[1:-1]
    return None


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    org: str,
    repo: str | None,
    accept_404: bool,
) -> httpx.Response:
    """GET `url` with retry on 429 / 5xx / timeout; raise GitHubScanError on exhaustion.

    Success = 2xx, or 404 when `accept_404` (probe path only). Non-retryable
    4xx (401 bad PAT, 403 forbidden, ...) fails fast without consuming the
    retry budget -- a bad PAT is not a transient upstream failure.
    """
    attempts = {"n": 0}

    async def _once() -> httpx.Response:
        attempts["n"] += 1
        started = time.perf_counter()
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "github_call_failed",
                extra={
                    "org": org,
                    "repo": repo,
                    "attempt": attempts["n"],
                    "duration_ms": duration_ms,
                    "error_kind": _classify_error_kind(exc),
                },
            )
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        status = resp.status_code
        if status == 429 or status >= 500:
            logger.warning(
                "github_call_failed",
                extra={
                    "org": org,
                    "repo": repo,
                    "attempt": attempts["n"],
                    "duration_ms": duration_ms,
                    "status_code": status,
                    "error_kind": "rate_limited" if status == 429 else "upstream_5xx",
                },
            )
            raise _RetryableStatus(status)
        return resp

    try:
        resp = await retry_with_backoff(_once, max_attempts=_RETRY_MAX_ATTEMPTS)
    except (httpx.HTTPError, _RetryableStatus) as exc:
        # `from None` suppresses the exception chain so the underlying
        # httpx / _RetryableStatus payload cannot re-surface downstream.
        raise GitHubScanError(_classify_error_kind(exc)) from None

    status = resp.status_code
    if status == 200:
        return resp
    if status == 404 and accept_404:
        return resp
    logger.warning(
        "github_call_failed",
        extra={
            "org": org,
            "repo": repo,
            "attempt": attempts["n"],
            "status_code": status,
            "error_kind": "non_retryable_status",
        },
    )
    raise GitHubScanError("non_retryable_status")


async def _list_org_repos(
    client: httpx.AsyncClient, org: str, headers: dict[str, str]
) -> tuple[list[dict[str, str]], int]:
    """Return `([{name, default_branch}], call_count)` for every repo in the org.

    Follows `Link: rel="next"` pagination until exhausted. Only `name` and
    `default_branch` are pulled off each response element -- the rest of the
    payload is discarded (never logged, NFR-security). A malformed element
    (missing / non-str `name` or `default_branch`) is treated as a fatal
    upstream contract failure rather than silently dropped -- protects
    `repos_total` from under-counting.
    """
    url: str | None = f"{_GITHUB_API_BASE}/orgs/{org}/repos?per_page={_PAGE_SIZE}&page=1"
    call_count = 0
    repos: list[dict[str, str]] = []
    while url is not None:
        resp = await _get_with_retry(
            client, url, headers=headers, org=org, repo=None, accept_404=False
        )
        call_count += 1
        for item in resp.json():
            name = item.get("name")
            default_branch = item.get("default_branch")
            if not isinstance(name, str) or not isinstance(default_branch, str):
                raise GitHubScanError("invalid_response")
            repos.append({"name": name, "default_branch": default_branch})
        url = _next_page_url(resp.headers.get("Link"))
    return repos, call_count


async def _probe_program_yaml(
    client: httpx.AsyncClient,
    org: str,
    repo: str,
    default_branch: str,
    headers: dict[str, str],
) -> bool:
    """True if `.harness/program.yaml` exists on `default_branch`, else False.

    Presence-only signal (Story Clarifications 2026-09-15 / D-03) -- the
    response body is discarded, never parsed.
    """
    url = (
        f"{_GITHUB_API_BASE}/repos/{org}/{repo}/contents/{_PROBE_PATH}"
        f"?ref={default_branch}"
    )
    resp = await _get_with_retry(
        client, url, headers=headers, org=org, repo=repo, accept_404=True
    )
    return resp.status_code == 200


async def _upsert_org_rollup(
    session: AsyncSession,
    *,
    repos_total: int,
    repos_installed: int,
    now: datetime,
) -> None:
    """Atomic upsert of the singleton `org_summary_rollup` row (FR-4).

    On INSERT, non-owned NOT-NULL columns are seeded to 0 to satisfy the
    schema (matches BED-03's `_build_org_summary` bootstrap shape). On
    CONFLICT, only the three columns this feature owns
    (`repos_total`, `repos_with_harness_installed`, `as_of_timestamp`) plus
    `updated_at` are refreshed -- BED-03's usage-derived columns are left
    untouched.
    """
    # D-02: accepted last-write-wins race with BED-03 rollup rebuild; see DECISIONS.md.
    insert_stmt = pg_insert(OrgSummaryRollup).values(
        id=str(uuid.uuid4()),
        org_id=_ORG_ID,
        programs_using_ai_count=0,
        programs_total=0,
        total_token_consumption=0,
        lines_of_code_generated=0,
        releases_using_harness=0,
        repos_with_harness_installed=repos_installed,
        repos_total=repos_total,
        as_of_timestamp=now,
        created_at=now,
        updated_at=now,
    )
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["org_id"],
        set_={
            "repos_with_harness_installed": insert_stmt.excluded.repos_with_harness_installed,
            "repos_total": insert_stmt.excluded.repos_total,
            "as_of_timestamp": insert_stmt.excluded.as_of_timestamp,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)


async def scan_org_repos(
    session: AsyncSession,
    *,
    github_org: str,
    github_token: str,
    http_client: httpx.AsyncClient | None = None,
) -> ScanReposResponse:
    """Scan the org, classify each repo by `.harness/program.yaml` presence,
    upsert `org_summary_rollup`, return the response DTO.

    Raises `GitHubScanError` after retry exhaustion or on a hung upstream
    (`httpx.TimeoutException`); the router (T-04) MUST NOT commit the
    request-scoped session on that path (FR-4 no-partial-write).

    `http_client` is an injection seam for tests / future concurrency
    tuning; when omitted, one is constructed per request with the
    10s connect/read timeout and closed via `try/finally`.
    """
    started = time.perf_counter()
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
    try:
        repos, list_calls = await _list_org_repos(client, github_org, headers)
        installed_count = 0
        probe_calls = 0
        for entry in repos:
            probe_calls += 1
            if await _probe_program_yaml(
                client, github_org, entry["name"], entry["default_branch"], headers
            ):
                installed_count += 1
    finally:
        if owns_client:
            await client.aclose()

    now = datetime.now(UTC)
    await _upsert_org_rollup(
        session,
        repos_total=len(repos),
        repos_installed=installed_count,
        now=now,
    )

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "admin_scan_completed",
        extra={
            "repos_total": len(repos),
            "repos_with_harness_installed": installed_count,
            "duration_ms": duration_ms,
            "github_api_calls": list_calls + probe_calls,
        },
    )
    return ScanReposResponse(
        repos_total=len(repos),
        repos_with_harness_installed=installed_count,
        as_of_timestamp=now,
    )
