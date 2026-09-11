"""Live bridge probe (manual, NOT part of the test suite): drives one real
SandboxBridge.prepare() against a running SwarmSandbox API and prints the
materialized workspace facts. Usage:

    SANDBOX_ENABLED=true SANDBOX_API_URL=http://127.0.0.1:5500 \
        .venv/bin/python -m webhook_receiver.sandbox_probe
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.prompt_queue import PromptInfo
from webhook_receiver.sandbox_bridge import SandboxBridge, SandboxBridgeError


async def run() -> int:
    os.environ.setdefault("OS_WEBHOOK_SECRET", "probe-unused")
    settings = Settings.from_env()
    store = EventStore()
    bridge = SandboxBridge(settings, store)
    info = PromptInfo(
        delivery_id="probe-1",
        repo="owner/target",
        event="issues",
        action="labeled",
        label="orchestration:probe",
        payload={"probe": True},
    )
    started = asyncio.get_running_loop().time()
    workspace = await bridge.prepare(info)
    elapsed = asyncio.get_running_loop().time() - started
    print(f"[probe] sandbox_id={workspace.sandbox_id}")
    print(f"[probe] container={workspace.container_name}")
    print(f"[probe] workspace={workspace.path}")
    print(f"[probe] elapsed={elapsed:.1f}s")
    git_config = (workspace.path / ".git" / "config").read_text(encoding="utf-8")
    token_free = "x-access-token" not in git_config
    print(f"[probe] git_config_token_free={token_free}")
    origin_gone = "origin" not in git_config
    print(f"[probe] origin_removed={origin_gone}")
    for marker in ("AGENTS.md", ".agents/skills/swarm/SKILL.md", ".zcode/agents/swarm-orchestrator.md"):
        print(f"[probe] asset {marker}: {(workspace.path / marker).is_file()}")
    for event in store.recent():
        print(f"[probe] event {event['type']}: {event['data']}")
    await bridge.release(workspace)
    print("[probe] released")
    return 0 if token_free and origin_gone else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except SandboxBridgeError as exc:
        print(f"[probe] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
