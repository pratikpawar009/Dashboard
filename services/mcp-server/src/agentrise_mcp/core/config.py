"""Config loading for the AgentRise MCP server (ING-04 · T-02).

Fail-fast on missing `AGENTRISE_INGEST_TOKEN` per FR-6 / D-06. Redacts the
token in `repr` / `str` per R-07 (NFR-Security).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

_TOKEN_ENV = "AGENTRISE_INGEST_TOKEN"
_BASE_URL_ENV = "AGENTRISE_INGEST_BASE_URL"
_DEFAULT_BASE_URL = "http://127.0.0.1:8000"

# Walk up from cwd to find a `.env`; canonical location is
# services/mcp-server/.env. `override=False` keeps ambient env winning.
load_dotenv(find_dotenv(usecwd=True), override=False)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    ingest_token: str
    ingest_base_url: str

    def __repr__(self) -> str:
        return (
            f"Config(ingest_token=<redacted>, ingest_base_url={self.ingest_base_url!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


def load_config() -> Config:
    """Load Config from environment. Raises ConfigError on missing token."""
    token = os.environ.get(_TOKEN_ENV)
    if token is None or token == "":
        raise ConfigError(f"{_TOKEN_ENV} is required but not set")

    base_url_raw = os.environ.get(_BASE_URL_ENV)
    if base_url_raw is None or base_url_raw == "":
        base_url = _DEFAULT_BASE_URL
    else:
        base_url = base_url_raw.rstrip("/")

    return Config(ingest_token=token, ingest_base_url=base_url)
