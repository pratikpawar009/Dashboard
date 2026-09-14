"""FR-8 JSON key allowlist — rejection matrix + acceptance surface (R-06, TC-29..TC-33)."""

from __future__ import annotations

import pytest

from agentrise_mcp.core.allowlist import AllowlistError, validate_json_key


@pytest.mark.parametrize(
    "key",
    [
        "",
        None,
    ],
    ids=["empty-string", "none"],
)
def test_reject_empty(key):
    with pytest.raises(AllowlistError) as exc:
        validate_json_key(key)
    assert repr(key) in str(exc.value)


@pytest.mark.parametrize(
    "key",
    [
        "a.b",
        "a[0]",
        "$.a",
        "#a",
        "@a",
        "!a",
        "a?",
        "a*",
    ],
)
def test_reject_injection_chars(key):
    with pytest.raises(AllowlistError) as exc:
        validate_json_key(key)
    msg = str(exc.value)
    assert repr(key) in msg
    assert "path-expression injection" in msg


@pytest.mark.parametrize(
    "key",
    [
        "a b",
        "a\tb",
        "a\nb",
    ],
    ids=["space", "tab", "newline"],
)
def test_reject_whitespace(key):
    with pytest.raises(AllowlistError) as exc:
        validate_json_key(key)
    msg = str(exc.value)
    assert repr(key) in msg
    assert "whitespace or control char" in msg


def test_reject_too_long():
    key = "x" * 129
    with pytest.raises(AllowlistError) as exc:
        validate_json_key(key)
    msg = str(exc.value)
    assert repr(key) in msg
    assert "128" in msg


@pytest.mark.parametrize(
    "key",
    [
        "count",
        "total_lines",
        "tool:generate",
        "snake_case-with-dash",
        "x",
        "a_b:c-d_e",
    ],
)
def test_accept_valid_keys(key):
    assert validate_json_key(key) is None


def test_accept_max_length_key():
    """Boundary — exactly 128 chars is accepted."""
    key = "x" * 128
    assert validate_json_key(key) is None
