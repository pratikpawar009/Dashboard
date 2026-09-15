"""Tests for HttpClient timeout + retry policy (T-04, NFR-Performance)."""

from __future__ import annotations

import json
import random
from unittest.mock import patch

import httpx
import pytest
import respx

from agentrise_mcp.core.http_client import HttpClient
from agentrise_mcp.core.retry import compute_backoff

BASE_URL = "http://api.test"
TOKEN = "secret-token"  # noqa: S105 — test fixture, not a real credential
PATH = "/v1/echo"


@pytest.fixture(autouse=True)
def _seed_random() -> None:
    random.seed(0)


@respx.mock
def test_post_json_success_first_attempt() -> None:
    route = respx.post(f"{BASE_URL}{PATH}").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with HttpClient(BASE_URL, TOKEN) as c:
        resp = c.post_json(PATH, {"hello": "world"})

    assert resp.status_code == 200
    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"
    # Compare parsed JSON, not raw bytes: httpx 0.28+ serializes without spaces
    # between separators. Contract is "payload sent as JSON", not exact whitespace.
    assert json.loads(sent.read()) == {"hello": "world"}


@respx.mock
def test_post_json_returns_4xx_no_retry() -> None:
    route = respx.post(f"{BASE_URL}{PATH}").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )
    with patch("agentrise_mcp.core.http_client.time.sleep") as sleep:
        with HttpClient(BASE_URL, TOKEN) as c:
            resp = c.post_json(PATH, {})

    assert resp.status_code == 401
    assert route.call_count == 1
    assert sleep.call_count == 0


@respx.mock
def test_post_json_returns_5xx_no_retry() -> None:
    route = respx.post(f"{BASE_URL}{PATH}").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with patch("agentrise_mcp.core.http_client.time.sleep") as sleep:
        with HttpClient(BASE_URL, TOKEN) as c:
            resp = c.post_json(PATH, {})

    assert resp.status_code == 500
    assert route.call_count == 1
    assert sleep.call_count == 0


@respx.mock
def test_post_json_retries_on_connect_error() -> None:
    route = respx.post(f"{BASE_URL}{PATH}").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with patch("agentrise_mcp.core.http_client.time.sleep") as sleep:
        with HttpClient(BASE_URL, TOKEN) as c:
            resp = c.post_json(PATH, {})

    assert resp.status_code == 200
    assert route.call_count == 3
    assert sleep.call_count == 2


@respx.mock
def test_post_json_exhausts_retries_then_raises() -> None:
    route = respx.post(f"{BASE_URL}{PATH}").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with patch("agentrise_mcp.core.http_client.time.sleep") as sleep:
        with HttpClient(BASE_URL, TOKEN) as c:
            with pytest.raises(httpx.ReadTimeout):
                c.post_json(PATH, {})

    assert route.call_count == 3
    # 2 sleeps between 3 attempts.
    assert sleep.call_count == 2
    total_slept = sum(call.args[0] for call in sleep.call_args_list)
    # Reset seed and reproduce the same backoff draws to compare exactly.
    random.seed(0)
    expected = compute_backoff(1) + compute_backoff(2)
    assert total_slept == pytest.approx(expected)


def test_compute_backoff_bounds() -> None:
    for _ in range(50):
        assert 0.5 <= compute_backoff(1) < 0.75
        assert 1.0 <= compute_backoff(2) < 1.25
        assert 4.0 <= compute_backoff(10) < 4.25


def test_compute_backoff_rejects_zero() -> None:
    with pytest.raises(ValueError):
        compute_backoff(0)


def test_client_repr_redacts_token() -> None:
    c = HttpClient("http://x", "secret-token")
    try:
        assert "secret-token" not in repr(c)
        assert "<redacted>" in repr(c)
    finally:
        c.close()
