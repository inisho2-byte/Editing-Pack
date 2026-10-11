"""Explicit read-only mailbox client. Prototype; not the old socket protocol."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import uuid

os.environ["PYTHONUTF8"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


import sys as _runtime_sys
for _parent in Path(__file__).resolve().parents:
    if (_parent / "runtime_paths.py").is_file():
        _runtime_sys.path.insert(0, str(_parent)); break
import runtime_paths as runtime

def paths():
    cache = runtime.native_mailbox()
    cache.mkdir(parents=True, exist_ok=True)
    return cache, cache / "resolve-lua-request.txt", cache / "resolve-lua-response.json", cache / "resolve-lua-pending.json"

COMMANDS = ("snapshot", "snapshot_once", "health", "capabilities", "stop", "connection_test_once", "media_inventory_once")


def prepare(command: str, ttl: int = 1800) -> dict:
    CACHE, REQUEST, RESPONSE, PENDING = paths()
    if command not in COMMANDS or not 1 <= ttl <= 1800:
        raise ValueError("Unsupported command or expiry")
    if PENDING.exists():
        previous = json.loads(PENDING.read_text(encoding="utf-8"))
        if previous["expires_at"] >= time.time():
            try:
                complete = json.loads(RESPONSE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                complete = {}
            if complete.get("id") != previous["id"]:
                raise RuntimeError("An uncompleted mailbox request already exists")
    pending = {"id": uuid.uuid4().hex, "command": command,
               "queued_at": int(time.time()), "expires_at": int(time.time()) + ttl}
    temporary = REQUEST.with_suffix(".tmp")
    temporary.write_text(f"editingpack1\n{pending['id']}\n{command}\n{pending['expires_at']}\n",
                         encoding="ascii", newline="\n")
    os.replace(temporary, REQUEST)
    PENDING.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    return pending


def collect(timeout: float = 0) -> dict:
    import math
    if not math.isfinite(timeout) or not 0 <= timeout <= 1800:
        raise ValueError("Timeout must be between 0 and 1800 seconds")
    CACHE, REQUEST, RESPONSE, PENDING = paths()
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = json.loads(RESPONSE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
        if result.get("id") == pending["id"]:
            if not isinstance(result.get("ok"), bool):
                raise RuntimeError("Invalid reply envelope")
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError("No matching live Resolve response yet")
        time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    queue = sub.add_parser("prepare")
    queue.add_argument("command", choices=COMMANDS)
    result = sub.add_parser("collect")
    result.add_argument("--timeout", type=float, default=0)
    runtime.common_args(parser)
    args = parser.parse_args()
    try:
        runtime.configure_args(args)
        output = prepare(args.command) if args.action == "prepare" else collect(args.timeout)
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0 if output.get("ok", True) else 1
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
