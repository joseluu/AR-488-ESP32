"""Entry point: `uv run python -m mcp_server` — starts FastMCP over stdio."""
from .server import mcp


if __name__ == "__main__":
    mcp.run()
