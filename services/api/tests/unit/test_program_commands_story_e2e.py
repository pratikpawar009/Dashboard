"""PGD-04 end-to-end story walkthrough — all 6 ACs in one real request sequence.

Not a replacement for the per-AC unit tests; this is the "does the story actually work"
check: one program, realistic multi-window data, one authenticated session, every AC
exercised against the real app + real Postgres in the order a user would hit them.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.test_program_commands_route import (
    AsyncClientFactory,
    _build_commands_app,
    _get_commands,
    _mint_dev_bypass_token,
    _seed_usage_events,
    _usage_event_row,
)


@pytest.mark.asyncio
async def test_story_walkthrough_all_six_acs(
    migrated_db,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    program_id = f"e2e-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    # 4 recent (in 7d), 3 mid (in 30d not 7d), 3 old (in 90d not 30d). Two users.
    rows = (
        [
            _usage_event_row(
                program_id=program_id,
                days_ago=1 + i % 3,
                now=now,
                command="/arh-implement",
                user="a@x.com",
            )
            for i in range(4)
        ]
        + [
            _usage_event_row(
                program_id=program_id,
                days_ago=20 + i,
                now=now,
                command="/arh-review",
                user="b@x.com",
            )
            for i in range(3)
        ]
        + [
            _usage_event_row(
                program_id=program_id, days_ago=50 + i, now=now, command="/arh-init", user="a@x.com"
            )
            for i in range(3)
        ]
    )
    await _seed_usage_events(test_session, rows)

    app = _build_commands_app(build_app, test_session)
    async with async_client_for(app) as client:
        token = await _mint_dev_bypass_token(client, role="developer")

        # AC-5 first: unauthenticated is rejected before anything else.
        assert (await _get_commands(client, program_id, token=None)).status_code == 401

        # AC-1: each range returns distinct command names + counts + a total.
        seen = {}
        for rng in ("7d", "30d", "90d"):
            r = await _get_commands(client, program_id, token=token, range_param=rng)
            assert r.status_code == 200, r.text
            seen[rng] = r.json()

        assert seen["7d"]["total_runs"] == "4"
        assert seen["30d"]["total_runs"] == "7"
        assert seen["90d"]["total_runs"] == "10"

        # The whole point of the story: ranges genuinely differ (R-6 guard, live).
        assert seen["7d"]["total_runs"] != seen["90d"]["total_runs"]
        assert {i["command"] for i in seen["90d"]["items"]} == {
            "/arh-implement",
            "/arh-review",
            "/arh-init",
        }

        # AC-1 (default): omitted range behaves as 30d.
        default = await _get_commands(client, program_id, token=token)
        assert default.status_code == 200
        assert default.json() == seen["30d"]

        # AC-3: ordered by count descending, and the top bar is 100% (max-of-range).
        counts = [i["count"] for i in seen["90d"]["items"]]
        assert counts == sorted(counts, reverse=True)
        assert seen["90d"]["items"][0]["barStyle"] == "width: 100%;"

        # AC-2: an invalid range is 400, never FastAPI's default 422.
        bad = await _get_commands(client, program_id, token=token, range_param="1y")
        assert bad.status_code == 400, f"got {bad.status_code}: {bad.text}"

        # AC-4: a different persona gets a byte-identical body (open-aggregate).
        cio = await _mint_dev_bypass_token(client, role="cio")
        other = await _get_commands(client, program_id, token=cio, range_param="90d")
        assert other.status_code == 200
        assert other.json() == seen["90d"]

        # D-02: an unknown program is 200-empty, not 404.
        unknown = await _get_commands(client, "no-such-program", token=token)
        assert unknown.status_code == 200
        assert unknown.json() == {"total_runs": "0", "items": []}

        # AC-6: the program total spans BOTH users, so it is not any one user's subset.
        # user a@x.com contributed 7 of the 10; the program reports all 10.
        assert seen["90d"]["total_runs"] == "10"
        implement = next(i for i in seen["90d"]["items"] if i["command"] == "/arh-implement")
        review = next(i for i in seen["90d"]["items"] if i["command"] == "/arh-review")
        assert review["count"] == 3, "b@x.com's events must be counted at program level"
        assert implement["count"] == 4
