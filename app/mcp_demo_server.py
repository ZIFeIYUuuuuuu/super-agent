from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Super Agent Demo MCP", json_response=True)


def _allowed_root() -> Path:
    """Return the filesystem root the demo server is allowed to touch."""
    return Path(os.getenv("MCP_ALLOWED_ROOT", Path.cwd())).resolve()


def _resolve_target(path: str) -> Path:
    """Resolve a user-supplied path and keep it inside the configured root."""
    root = _allowed_root()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path is outside the allowed MCP root: {target}") from exc
    return target


@mcp.tool()
def dangerous_delete_file(path: str) -> dict[str, object]:
    """Delete one file inside the configured root directory."""
    target = _resolve_target(path)
    if not target.exists():
        return {
            "summary": f"File did not exist: {target}",
            "path": str(target),
            "deleted": False,
        }
    if target.is_dir():
        raise ValueError("dangerous_delete_file only supports files, not directories")
    target.unlink()
    return {
        "summary": f"Deleted file {target}",
        "path": str(target),
        "deleted": True,
    }


@mcp.tool()
def safe_read_file(path: str) -> dict[str, object]:
    """Read a small text preview from one file inside the configured root."""
    target = _resolve_target(path)
    if not target.exists():
        raise ValueError(f"File does not exist: {target}")
    if target.is_dir():
        raise ValueError("safe_read_file only supports files, not directories")
    preview = target.read_text(encoding="utf-8", errors="replace")[:500]
    return {
        "summary": f"Read {len(preview)} preview characters from {target.name}",
        "path": str(target),
        "content_preview": preview,
    }


if __name__ == "__main__":
    mcp.run(transport=os.getenv("MCP_TRANSPORT", "stdio"))
