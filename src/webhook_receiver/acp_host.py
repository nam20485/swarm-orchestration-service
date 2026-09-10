"""ACP host (Phase 2): drives one cold ``opencode`` session per PromptInfo.

Plan §7 Phase 2 / §3.2: for each dequeued envelope the host spawns
``<opencode> acp --cwd <workspace>`` over stdio JSON-RPC (Agent Client
Protocol), initializes, opens a session, sends one prompt, streams the
``session/update`` notifications into the :class:`EventStore`, and collects
the stop reason. No ``opencode serve`` container exists anywhere; the
process is killed on every exit path (timeout ladder + context-manager
kill, per ``spikes/acp/host_spike.py``). One client only (opencode) — this
is deliberately not a plugin system (Simplicity First).

**Model/agent config is never pinned host-side** (plan §5 Decision 10):
model, tools, and MCP servers come from opencode's own config (global +
the workspace ``opencode.json`` written here, which only carries the
fail-closed ``permission`` deny-list from ``Settings.acp_denied_tools``).

**EventStore contract (plan §5 Decision 7 — protocol events only; stable
names; every event carries ``run_id`` = the PromptInfo id):**

===========================  =====================================================
Event type                   Data
===========================  =====================================================
``agent_session_started``    session_id, protocol_version
``agent_message_chunk``      text (agent reply deltas)
``agent_tool_call``          tool_call_id, title, kind, status
``agent_usage``              used, size, cost
``agent_permission``         title, action, reason (policy decision)
``agent_finished``           session_id, stop_reason, ok, error (on failure)
===========================  =====================================================

Other ``session/update`` kinds (plan deltas, mode changes, thought chunks,
available commands) are consumed and ignored — extend the mapping here if
the dashboard needs them.

**Prompt seam (Phase 3):** the envelope's own ``prompt`` wins when present —
the listener fills it with the open-ended orchestration prompt at enqueue
time (``prompt_builder.build_orchestration_prompt``). The derived
pipeline-check instruction below remains only as the fallback for
envelopes built outside the listener (smoke overrides, direct host use).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acp import PROTOCOL_VERSION, spawn_agent_process
from acp.schema import (
    ClientCapabilities,
    Implementation,
    TextContentBlock,
)

from webhook_receiver.acp_policy import PermissionDecision, decide, respond
from webhook_receiver.prompt_queue import PromptInfo

if TYPE_CHECKING:
    from webhook_receiver.config import Settings
    from webhook_receiver.event_store import EventStore

logger = logging.getLogger(__name__)

# Light stderr redaction (same shape as the spike): never echo credentials.
_REDACT_RE = re.compile(
    r"(?i)((?:api[_-]?key|authorization|token|secret)\s*[=:]\s*)\S+"
)
# Grace window for killing the agent process during shutdown/cleanup.
_KILL_GRACE_SECONDS = 5.0


class AcpHostError(RuntimeError):
    """The ACP session failed to launch, timed out, or broke protocol."""


@dataclass(frozen=True)
class AcpRunResult:
    """Outcome of one cold session, merged into ``prompt_consumed``."""

    session_id: str
    stop_reason: str
    workspace: str


def resolve_opencode_bin(settings: Settings) -> str:
    """Resolve the opencode binary: explicit setting, PATH, then default."""
    if settings.acp_opencode_bin:
        return settings.acp_opencode_bin
    found = shutil.which("opencode")
    if found:
        return found
    default = str(Path.home() / ".opencode" / "bin" / "opencode")
    if Path(default).is_file():
        return default
    raise AcpHostError(
        "opencode binary not found (set ACP_OPENCODE_BIN or install opencode)"
    )


def build_prompt(info: PromptInfo) -> str:
    """Prompt for one envelope.

    Phase 3 seam: a filled ``info.prompt`` (orchestration prompt) wins;
    until then derive a minimal pipeline-check instruction from the
    envelope fields.
    """
    if info.prompt is not None:
        return info.prompt
    return (
        f"GitHub webhook received for repository '{info.repo}': "
        f"event={info.event}, action={info.action}, label='{info.label}', "
        f"delivery_id={info.delivery_id}. This is an automated pipeline "
        f"check: reply with one short sentence acknowledging the event, "
        f"then end your turn. Do not modify any files."
    )


class HostClient:
    """ACP client callbacks: session_update mapping + permission policy.

    Duck-typed like the spike client: only ``session_update`` and
    ``request_permission`` are implemented; fs/terminal/elicitation
    capabilities are declared false, so a well-behaved agent never calls
    them.
    """

    def __init__(self, settings: Settings, store: EventStore, run_id: str) -> None:
        self._settings = settings
        self._store = store
        self._run_id = run_id

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        kind = getattr(update, "session_update", type(update).__name__)
        if kind == "agent_message_chunk":
            text = getattr(update.content, "text", None)
            if text:
                self._store.emit(
                    "agent_message_chunk", run_id=self._run_id, text=text
                )
            return
        if kind in ("tool_call", "tool_call_update"):
            self._store.emit(
                "agent_tool_call",
                run_id=self._run_id,
                tool_call_id=getattr(update, "tool_call_id", None),
                title=getattr(update, "title", None),
                kind=getattr(update, "kind", None),
                status=getattr(update, "status", None),
            )
            return
        if kind == "usage_update":
            self._store.emit(
                "agent_usage",
                run_id=self._run_id,
                used=getattr(update, "used", None),
                size=getattr(update, "size", None),
                cost=getattr(update, "cost", None),
            )
            return
        # Plan deltas, mode changes, thought/command updates: intentionally
        # unmapped (module docstring). Debug-log only.
        logger.debug(
            "ACP session_update kind=%s ignored run_id=%s", kind, self._run_id
        )

    async def request_permission(
        self, session_id: str, tool_call: Any, options: list[Any], **_: Any
    ) -> Any:
        decision: PermissionDecision = decide(tool_call, self._settings)
        title = getattr(tool_call, "title", None)
        logger.info(
            "ACP permission run_id=%s title=%s action=%s (%s)",
            self._run_id,
            title,
            decision.action,
            decision.reason,
        )
        self._store.emit(
            "agent_permission",
            run_id=self._run_id,
            title=title,
            action=decision.action,
            reason=decision.reason,
        )
        return respond(options, decision)


class AcpHost:
    """Runs one cold ACP session per :class:`PromptInfo` envelope."""

    def __init__(self, settings: Settings, store: EventStore) -> None:
        self._settings = settings
        self._store = store

    async def run(self, info: PromptInfo) -> AcpRunResult:
        """Drive one prompt end-to-end; raises :class:`AcpHostError` on failure."""
        bin_path = resolve_opencode_bin(self._settings)
        workspace = self._prepare_workspace(info)
        client = HostClient(self._settings, self._store, run_id=info.id)
        step = self._settings.acp_step_timeout
        prompt_timeout = self._settings.acp_prompt_timeout
        response: Any = None
        session_id: str | None = None
        conn: Any = None
        proc: Any = None
        drainer: asyncio.Task[None] | None = None

        async def drain_stderr() -> None:
            stream = proc.stderr if proc is not None else None
            if stream is None:
                return
            while True:
                line = await stream.readline()
                if not line:
                    return
                logger.debug(
                    "opencode stderr run_id=%s: %s",
                    info.id,
                    _REDACT_RE.sub(r"\1<redacted>", line.decode(errors="replace").rstrip()),
                )

        try:
            async with asyncio.timeout(step * 3 + prompt_timeout):
                async with spawn_agent_process(
                    client, bin_path, "acp", "--cwd", str(workspace)
                ) as (conn, proc):
                    drainer = asyncio.create_task(drain_stderr())
                    init = await asyncio.wait_for(
                        conn.initialize(
                            PROTOCOL_VERSION,
                            client_capabilities=ClientCapabilities(),
                            client_info=Implementation(
                                name="swarm-orchestration-host", version="0.1.0"
                            ),
                        ),
                        step,
                    )
                    session = await asyncio.wait_for(
                        conn.new_session(cwd=str(workspace)), step
                    )
                    session_id = session.session_id
                    self._store.emit(
                        "agent_session_started",
                        run_id=info.id,
                        session_id=session_id,
                        protocol_version=init.protocol_version,
                    )
                    response = await asyncio.wait_for(
                        conn.prompt(
                            session_id,
                            [TextContentBlock(type="text", text=build_prompt(info))],
                        ),
                        prompt_timeout,
                    )
        except asyncio.CancelledError:
            raise  # shutdown: cleanup below, no run-level event
        except Exception as exc:
            error = (
                f"acp run timed out after {step * 3 + prompt_timeout:.0f}s"
                if isinstance(exc, TimeoutError)
                else f"{type(exc).__name__}: {exc}"
            )
            self._store.emit(
                "agent_finished",
                run_id=info.id,
                session_id=session_id,
                stop_reason=None,
                ok=False,
                error=error,
            )
            raise AcpHostError(f"acp session failed for delivery {info.delivery_id}: {error}") from exc
        finally:
            if drainer is not None and not drainer.done():
                drainer.cancel()
                await asyncio.gather(drainer, return_exceptions=True)
            if proc is not None and proc.returncode is None:
                # Kill-on-exit orphan hygiene (spike pattern). The kill is
                # the guarantee; reaping gets a short grace window and may
                # be abandoned by a racing shutdown cancel.
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), _KILL_GRACE_SECONDS)
                except Exception:
                    logger.warning(
                        "opencode process not reaped cleanly run_id=%s", info.id
                    )

        stop_reason = getattr(response, "stop_reason", None)
        self._store.emit(
            "agent_finished",
            run_id=info.id,
            session_id=session_id,
            stop_reason=stop_reason,
            ok=True,
        )
        return AcpRunResult(
            session_id=session_id or "",
            stop_reason=stop_reason or "",
            workspace=str(workspace),
        )

    def _prepare_workspace(self, info: PromptInfo) -> Path:
        """Fresh scratch cwd for the agent; never the repo itself."""
        root = (
            Path(self._settings.acp_workspace_root)
            if self._settings.acp_workspace_root
            else Path("/tmp") / "swarm-acp-workspaces"
        )
        workspace = root / info.id
        workspace.mkdir(parents=True, exist_ok=True)
        if self._settings.acp_denied_tools:
            config = {
                "$schema": "https://opencode.ai/config.json",
                "permission": {tool: "deny" for tool in self._settings.acp_denied_tools},
            }
            (workspace / "opencode.json").write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )
        return workspace
