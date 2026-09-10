#!/usr/bin/env python3
"""Phase 0.1 ACP spike host: drive `opencode acp` over stdio JSON-RPC.

Modes:
  happy         initialize -> new_session -> one trivial prompt -> stopReason (default)
  deny          opencode permission.bash=ask forces session/request_permission;
                the host auto-selects the reject option; agent must finish cleanly
  deny-config   opencode permission.bash=deny so no request ever fires
                (belt-and-braces); the tool call must not execute

Transcript log: /tmp/acp-spike/<mode>-<timestamp>.log
Exit code: 0 = mode's success criteria met; 1 = protocol failure or timeout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

from acp import PROTOCOL_VERSION, spawn_agent_process
from acp.schema import (
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    Implementation,
    RequestPermissionResponse,
    TextContentBlock,
)

SCRATCH_ROOT = Path("/tmp/acp-spike")
STEP_TIMEOUT = 30.0
PROMPT_TIMEOUT = 180.0
REJECT_KINDS = ("reject_once", "reject_always")

# opencode.json written into the scratch cwd to force the permission behavior.
# Bash is the tool the deny prompts ask the agent to use.
PERMISSION_CONFIG = {
    "deny": {"permission": {"bash": "ask"}},
    "deny-config": {"permission": {"bash": "deny"}},
}

DENY_PROMPT = (
    "Use the bash tool to run exactly this command: echo acp-deny-probe. "
    "Then report the command's output."
)
PROMPTS = {
    "happy": "Reply with exactly: ACP-OK",
    "deny": DENY_PROMPT,
    "deny-config": DENY_PROMPT,
}

_REDACT_RE = re.compile(r"(?i)((?:api[_-]?key|authorization|token|secret)\s*[=:]\s*)\S+")


class Transcript:
    """Timestamped JSON-lines transcript to a /tmp file, echoed compactly to stdout."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("w", encoding="utf-8")
        self.t0 = time.monotonic()

    def log(self, event: str, **fields: object) -> None:
        record = {"t": round(time.monotonic() - self.t0, 3), "event": event, **fields}
        line = json.dumps(record, default=str)
        self._fh.write(line + "\n")
        self._fh.flush()
        print(line)

    def raw(self, source: str, line: str) -> None:
        scrubbed = _REDACT_RE.sub(r"\1<redacted>", line.rstrip())
        self._fh.write(f"{source}: {scrubbed}\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class SpikeClient:
    """ACP Client callbacks: session_update + request_permission.

    Other Client methods (fs/*, terminal/*, elicitation) are intentionally absent:
    we declare those capabilities false in initialize, so a well-behaved agent
    never calls them and the router answers method-not-found if it does.
    """

    def __init__(self, tr: Transcript, mode: str) -> None:
        self.tr = tr
        self.mode = mode
        self.update_kinds: list[str] = []
        self.agent_text: list[str] = []
        self.tool_calls: list[dict] = []
        self.permission_requests: list[dict] = []

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        kind = getattr(update, "session_update", type(update).__name__)
        self.update_kinds.append(kind)
        if kind == "agent_message_chunk":
            block = update.content
            text = getattr(block, "text", None)
            if text:
                self.agent_text.append(text)
                self.tr.log("agent_text", text=text)
            else:
                self.tr.log("session_update", kind=kind)
            return
        if kind in ("tool_call", "tool_call_update"):
            entry = {
                "id": getattr(update, "tool_call_id", None),
                "title": getattr(update, "title", None),
                "status": getattr(update, "status", None),
                "raw_input": getattr(update, "raw_input", None),
            }
            self.tool_calls.append(entry)
            self.tr.log("tool_call", **entry)
            return
        self.tr.log("session_update", kind=kind)

    async def request_permission(self, session_id: str, tool_call, options, **kwargs) -> RequestPermissionResponse:
        option_kinds = [o.kind for o in options]
        record = {"title": getattr(tool_call, "title", None), "option_kinds": option_kinds}
        self.permission_requests.append(record)
        self.tr.log("request_permission", **record)
        if self.mode in ("deny", "deny-config"):
            reject = next((o for o in options if o.kind in REJECT_KINDS), None)
            if reject is not None:
                outcome = AllowedOutcome(outcome="selected", option_id=reject.option_id)
                self.tr.log("permission_outcome", selected=reject.kind, option_id=reject.option_id)
            else:
                outcome = DeniedOutcome(outcome="cancelled")
                self.tr.log("permission_outcome", selected="cancelled (no reject option offered)")
        else:
            # happy mode: unexpected; pick allow_once so the run can still proceed.
            allow = next((o for o in options if o.kind == "allow_once"), options[0])
            outcome = AllowedOutcome(outcome="selected", option_id=allow.option_id)
            self.tr.log("permission_outcome", selected=getattr(allow, "kind", "?"), unexpected_in_mode=self.mode)
        return RequestPermissionResponse(outcome=outcome)


def setup_scratch(mode: str, scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    config = PERMISSION_CONFIG.get(mode)
    if config:
        opencode_json = {"$schema": "https://opencode.ai/config.json", **config}
        (scratch / "opencode.json").write_text(json.dumps(opencode_json, indent=2), encoding="utf-8")


async def drain_stderr(process: asyncio.subprocess.Process, log: Transcript) -> None:
    assert process.stderr is not None
    while True:
        line = await process.stderr.readline()
        if not line:
            return
        log.raw("[agent-stderr]", line.decode(errors="replace"))


async def run(mode: str, scratch: Path) -> int:
    opencode = shutil.which("opencode") or str(Path.home() / ".opencode" / "bin" / "opencode")
    log = Transcript(SCRATCH_ROOT / f"{mode}-{time.strftime('%Y%m%d-%H%M%S')}.log")
    setup_scratch(mode, scratch)
    client = SpikeClient(log, mode)
    process: asyncio.subprocess.Process | None = None
    try:
        log.log("spawn", mode=mode, command=f"{opencode} acp --cwd {scratch}", scratch=str(scratch))
        overall = asyncio.timeout(STEP_TIMEOUT * 3 + PROMPT_TIMEOUT)
        async with overall:
            async with spawn_agent_process(client, opencode, "acp", "--cwd", str(scratch)) as (conn, proc):
                process = proc
                drainer = asyncio.create_task(drain_stderr(proc, log))
                init = await asyncio.wait_for(
                    conn.initialize(
                        PROTOCOL_VERSION,
                        client_capabilities=ClientCapabilities(),
                        client_info=Implementation(name="acp-spike-host", version="0.1.0"),
                    ),
                    STEP_TIMEOUT,
                )
                log.log(
                    "initialized",
                    protocol_version=init.protocol_version,
                    agent_capabilities=init.agent_capabilities.model_dump(exclude_none=True, by_alias=True),
                    auth_methods=[m.name for m in (init.auth_methods or [])],
                )
                session = await asyncio.wait_for(conn.new_session(cwd=str(scratch)), STEP_TIMEOUT)
                log.log("session_new", session_id=session.session_id)
                response = await asyncio.wait_for(
                    conn.prompt(session.session_id, [TextContentBlock(type="text", text=PROMPTS[mode])]),
                    PROMPT_TIMEOUT,
                )
                log.log("prompt_returned", stop_reason=response.stop_reason)
        if not drainer.done():
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        log.log("agent_exited", returncode=process.returncode if process else None)
        return evaluate(mode, client, response.stop_reason, log)
    except (TimeoutError, asyncio.TimeoutError) as exc:
        log.log("timeout", error=str(exc))
        return 1
    except Exception as exc:  # protocol error: JSON-RPC error response, spawn failure, ...
        log.log("protocol_error", error=type(exc).__name__, detail=str(exc))
        return 1
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        log.log("done")
        log.close()


def evaluate(mode: str, client: SpikeClient, stop_reason: str, log: Transcript) -> int:
    """Check the mode's success criteria; return exit code."""
    if mode == "happy":
        ok = stop_reason == "end_turn" and "ACP-OK" in "".join(client.agent_text)
        log.log("verdict", ok=ok, agent_text="".join(client.agent_text))
        return 0 if ok else 1
    if mode == "deny":
        rejected = len(client.permission_requests) >= 1 and stop_reason in ("end_turn", "refusal")
        log.log(
            "verdict",
            ok=rejected,
            permission_requests=len(client.permission_requests),
            stop_reason=stop_reason,
        )
        return 0 if rejected else 1
    # deny-config: no request may fire, and bash must not have run.
    ran = any(
        tc["status"] == "completed" and "acp-deny-probe" in str(tc.get("raw_output", ""))
        for tc in client.tool_calls
    )
    ok = len(client.permission_requests) == 0 and not ran and stop_reason in ("end_turn", "refusal")
    log.log(
        "verdict",
        ok=ok,
        permission_requests=len(client.permission_requests),
        bash_executed=ran,
        tool_calls=client.tool_calls,
        stop_reason=stop_reason,
    )
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=list(PROMPTS), default="happy")
    parser.add_argument("--scratch", type=Path, default=None, help="agent cwd (default /tmp/acp-spike/<mode>)")
    args = parser.parse_args()
    scratch = args.scratch or SCRATCH_ROOT / args.mode
    raise SystemExit(asyncio.run(run(args.mode, scratch)))


if __name__ == "__main__":
    main()
