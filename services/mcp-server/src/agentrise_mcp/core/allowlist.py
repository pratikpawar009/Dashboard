"""Glob-pattern and JSON-key allowlist validators (ING-04 FR-7 / FR-8 / R-06).

Pure validators — no I/O, no logging, no side effects. Callers apply these
BEFORE any filesystem enumeration (T-07 source resolvers) or JSON traversal.
Symlink-escape and workspace-root containment checks land at the resolver tier
(T-06 / T-07) after `pathlib.Path.resolve()`; this module only inspects the
literal user-supplied strings.
"""

from __future__ import annotations

import os
import re

__all__ = ["AllowlistError", "validate_glob", "validate_json_key"]

# Shell metacharacters banned in glob patterns (fnmatch supports *, **, ?, [...] only).
_GLOB_SHELL_METACHARS: frozenset[str] = frozenset("`$|;&><")

# Path-expression injection chars banned in JSON key selectors (no JSONPath / JMESPath).
_JSON_KEY_INJECTION_CHARS: frozenset[str] = frozenset("[].$#@!?*")

_JSON_KEY_MAX_LEN = 128

# Split path into components on either separator so `..` traversal is caught
# regardless of the runtime OS's os.sep.
_PATH_SEP_RE = re.compile(r"[/\\]" if os.sep != "/" else r"/")


class AllowlistError(ValueError):
    """Raised when a user-supplied glob pattern or JSON key fails allowlist checks."""


def validate_glob(pattern: str) -> None:
    """Validate a glob pattern against FR-7's rejection matrix.

    Raises `AllowlistError` with a message naming the rejection reason and quoting
    the offending pattern. Passes silently when OK.
    """
    if pattern is None or pattern == "":
        raise AllowlistError(f"empty glob pattern: {pattern!r}")

    if "\x00" in pattern:
        raise AllowlistError(f"null byte in glob pattern: {pattern!r}")

    if pattern.startswith("/") or pattern.startswith("\\"):
        raise AllowlistError(f"absolute path not allowed in glob pattern: {pattern!r}")

    if "~" in pattern:
        raise AllowlistError(f"home-expansion (~) not allowed in glob pattern: {pattern!r}")

    for ch in pattern:
        if ch in _GLOB_SHELL_METACHARS:
            raise AllowlistError(
                f"shell metacharacter {ch!r} not allowed in glob pattern: {pattern!r}"
            )

    for segment in _PATH_SEP_RE.split(pattern):
        if segment == "..":
            raise AllowlistError(
                f"parent-directory traversal ('..') not allowed in glob pattern: {pattern!r}"
            )


def validate_json_key(key: str) -> None:
    """Validate a JSON key / field selector against FR-8's rejection matrix.

    Raises `AllowlistError` with a message naming the rejection reason and quoting
    the offending key. Passes silently when OK.
    """
    if key is None or key == "":
        raise AllowlistError(f"empty JSON key: {key!r}")

    if len(key) > _JSON_KEY_MAX_LEN:
        raise AllowlistError(
            f"JSON key exceeds {_JSON_KEY_MAX_LEN} chars ({len(key)}): {key!r}"
        )

    for ch in key:
        if ch in _JSON_KEY_INJECTION_CHARS:
            raise AllowlistError(
                f"path-expression injection char {ch!r} not allowed in JSON key: {key!r}"
            )
        if ch == " " or not ch.isprintable():
            raise AllowlistError(
                f"whitespace or control char {ch!r} not allowed in JSON key: {key!r}"
            )
