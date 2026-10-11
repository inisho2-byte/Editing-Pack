"""MCP prototype: native reads plus one guarded empty-project connection test."""

# Resolve only this standalone toolkit's owned shared runtime module.
import sys as _runtime_sys
from pathlib import Path as _RuntimePath
for _runtime_parent in _RuntimePath(__file__).resolve().parents:
    if (_runtime_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_runtime_parent))
        break
import runtime_paths as runtime
import os
import threading

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from mcp.server.fastmcp import FastMCP
from resolve_lua_client import paths, prepare, collect
import json
import time

server = FastMCP("Editing-Pack Resolve Lua (bounded prototype)")
request_lock = threading.Lock()


def request(command: str) -> dict:
    with request_lock:
        try:
            status = json.loads((paths()[0] / "resolve-lua-status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("Start resolve_bridge.lua in the Resolve Console first") from exc
        if status.get("state") != "ready" or status.get("expires_at", 0) <= time.time():
            raise RuntimeError("Lua session is stopped or expired; start it from Resolve Console")
        prepare(command, ttl=30)
        result = collect(timeout=10)
        if result.get("session_id") != status.get("session_id"):
            raise RuntimeError("Resolve bridge session changed; inspect before retrying")
        if result.get("ok") is not True:
            raise RuntimeError("Native Lua request failed: " + str(result.get("error", "invalid reply")))
        return result


@server.tool()
def resolve_lua_snapshot() -> dict:
    """Read actual Resolve version, product, current project and timeline metadata."""
    return request("snapshot")


@server.tool()
def resolve_lua_health() -> dict:
    """Read live Resolve version via the Lua mailbox, not a cached connection status."""
    return request("health")


@server.tool()
def resolve_lua_capabilities() -> dict:
    """Inspect the actual in-app Fusion UI dispatch facilities; no project changes."""
    return request("capabilities")


@server.tool()
def resolve_lua_connection_test() -> dict:
    """In the explicitly configured verified empty project only: create a temporary timeline, add/read
    a marker, then delete that exact timeline. Reject any existing timelines;
    preserve all imported media and folders.
    This operation stops its Console session after responding.
    """
    return request("connection_test_once")


@server.tool()
def resolve_lua_stop() -> dict:
    """Stop the bounded read-only Console bridge session."""
    return request("stop")


if __name__ == "__main__":
    server.run(transport="stdio")
