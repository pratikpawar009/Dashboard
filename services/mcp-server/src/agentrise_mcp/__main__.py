"""`python -m agentrise_mcp` entry — delegates to `server.main()`."""

from __future__ import annotations

import sys

from agentrise_mcp.server import main

if __name__ == "__main__":
    sys.exit(main())
