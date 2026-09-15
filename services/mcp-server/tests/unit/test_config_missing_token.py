"""Negative-path and boundary tests for `load_config` (ING-04 · T-02)."""

from __future__ import annotations

import pytest

from agentrise_mcp.core.config import Config, ConfigError, load_config


def test_load_config_raises_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTRISE_INGEST_TOKEN", raising=False)
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert "AGENTRISE_INGEST_TOKEN" in str(excinfo.value)


def test_load_config_raises_when_token_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRISE_INGEST_TOKEN", "")
    with pytest.raises(ConfigError) as excinfo:
        load_config()
    assert "AGENTRISE_INGEST_TOKEN" in str(excinfo.value)


def test_load_config_ok_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTRISE_INGEST_TOKEN", "abc123")
    monkeypatch.delenv("AGENTRISE_INGEST_BASE_URL", raising=False)
    cfg = load_config()
    assert cfg.ingest_token == "abc123"
    assert cfg.ingest_base_url == "http://127.0.0.1:8000"


def test_load_config_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRISE_INGEST_TOKEN", "abc123")
    monkeypatch.setenv("AGENTRISE_INGEST_BASE_URL", "http://api.test/")
    cfg = load_config()
    assert cfg.ingest_base_url == "http://api.test"


def test_config_repr_redacts_token() -> None:
    cfg = Config(ingest_token="abc123", ingest_base_url="http://api.test")
    assert "abc123" not in repr(cfg)
    assert "abc123" not in str(cfg)
