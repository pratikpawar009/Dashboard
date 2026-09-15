"""Unit tests for the glob-count source resolver (ING-04 T-07)."""

from __future__ import annotations

import os

import pytest

from agentrise_mcp.core.allowlist import AllowlistError
from agentrise_mcp.core.profile import ArtifactSource
from agentrise_mcp.sources.glob_count import SourceError, resolve


def test_counts_matches(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("a")
    (docs / "b.md").write_text("b")
    (tmp_path / "README.md").write_text("readme")

    source = ArtifactSource(kind="glob-count", path="docs", glob="*.md")
    assert resolve(source, tmp_path) == 2


def test_no_matches_returns_zero(tmp_path):
    source = ArtifactSource(kind="glob-count", path="nothing", glob="*.md")
    assert resolve(source, tmp_path) == 0


def test_excludes_directories(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "sub").mkdir()
    (docs / "a.md").write_text("a")

    source = ArtifactSource(kind="glob-count", path="docs", glob="*")
    assert resolve(source, tmp_path) == 1


def test_rejects_traversal_glob(tmp_path):
    source = ArtifactSource(kind="glob-count", path="docs", glob="../etc/*")
    with pytest.raises(AllowlistError):
        resolve(source, tmp_path)


def test_rejects_absolute_glob(tmp_path):
    source = ArtifactSource(kind="glob-count", path="/etc", glob="*")
    with pytest.raises(AllowlistError):
        resolve(source, tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics differ on Windows")
def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / f"outside_{tmp_path.name}.md"
    outside.write_text("secret")
    try:
        link = tmp_path / "leak.md"
        link.symlink_to(outside)

        source = ArtifactSource(kind="glob-count", path=".", glob="*.md")
        with pytest.raises(SourceError, match="escaped workspace_root"):
            resolve(source, tmp_path)
    finally:
        if outside.exists():
            outside.unlink()


def test_exclude_filter(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("a")
    (docs / "b.md").write_text("b")
    (docs / "skip.md").write_text("skip")

    source = ArtifactSource(
        kind="glob-count",
        path="docs",
        glob="*.md",
        exclude=("**/skip.md",),
    )
    assert resolve(source, tmp_path) == 2
