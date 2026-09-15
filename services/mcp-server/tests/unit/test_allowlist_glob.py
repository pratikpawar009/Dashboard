"""FR-7 glob allowlist — rejection matrix + acceptance surface (R-06, TC-25..TC-28)."""

from __future__ import annotations

import pytest

from agentrise_mcp.core.allowlist import AllowlistError, validate_glob


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        None,
    ],
    ids=["empty-string", "none"],
)
def test_reject_empty(pattern):
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    assert repr(pattern) in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "../a",
        "a/../b",
        "**/../c",
        "./../x",
    ],
)
def test_reject_parent_traversal(pattern):
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    msg = str(exc.value)
    assert repr(pattern) in msg
    assert ".." in msg


@pytest.mark.parametrize(
    "pattern",
    [
        "/etc/passwd",
        "\\Windows\\System32",
    ],
)
def test_reject_absolute(pattern):
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    assert repr(pattern) in str(exc.value)
    assert "absolute" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "~/secret",
        "a/~/b",
    ],
)
def test_reject_home_expansion(pattern):
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    assert repr(pattern) in str(exc.value)
    assert "~" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "a`b",
        "a$b",
        "a|b",
        "a;b",
        "a&b",
        "a>b",
        "a<b",
    ],
)
def test_reject_shell_metachars(pattern):
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    assert repr(pattern) in str(exc.value)
    assert "shell metacharacter" in str(exc.value)


def test_reject_null_byte():
    pattern = "a\x00b"
    with pytest.raises(AllowlistError) as exc:
        validate_glob(pattern)
    assert repr(pattern) in str(exc.value)
    assert "null byte" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        "**/*.md",
        "docs/**/*.yaml",
        "src/tests/test_*.py",
        "a/b/c.txt",
        "x[!abc].py",
        "q?.log",
    ],
)
def test_accept_valid_patterns(pattern):
    assert validate_glob(pattern) is None
