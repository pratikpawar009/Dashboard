"""Unit tests for the constant source resolver (ING-04 T-07)."""

from __future__ import annotations

import pytest

from agentrise_mcp.core.profile import ArtifactSource
from agentrise_mcp.sources.constant import SourceError, resolve


def test_returns_value(tmp_path):
    source = ArtifactSource(kind="constant", value=42)
    assert resolve(source, tmp_path) == 42


def test_missing_value_raises(tmp_path):
    source = ArtifactSource(kind="constant", value=None)
    with pytest.raises(SourceError, match="requires 'value'"):
        resolve(source, tmp_path)
