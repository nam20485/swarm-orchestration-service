"""ACP host (Phase 2): drives one cold ``opencode`` session per PromptInfo.

Plan §7 Phase 2 / §3.2: for each dequeued envelope the host spawns
``<opencode> acp`` over stdio JSON-RPC (Agent Client Protocol) with the
workspace as the process cwd (opencode >= 2.0 removed the ``--cwd`` flag;
the cwd is set on the process and again on ``session/new``), initializes,
opens a session, sends one prompt, streams the
``session/update`` notifications into the :class:`EventStore`, and collects
the stop reason. No ``opencode serve`` container exists anywhere; the
process is killed on every exit path (timeout ladder + context-manager
kill, per ``spikes/acp/host_spike.py``). One client only (opencode) — this
is deliberately not a plugin system (Simplicity First).

**Model/agent config is never pinned host-side** (plan §5 Decision 10):
model, tools, and MCP servers come from opencode's own config (global +
the workspace ``opencode.json`` written here for bare workspaces only —
never a lived-in checkout — carrying the fail-closed ``permission``
deny-list from ``Settings.acp_denied_tools``).

**EventStore contract (plan §5 Decision 7 — protocol events only; stable
names; every event carries ``run_id`` = the PromptInfo id). ALL-traces
(``docs/plans/webui-plan.md`` W0): every ``session/update`` kind maps to an
event and nothing is filtered server-side — the UI filters; unrecognized
kinds pass through as ``agent_update`` instead of being dropped:**

===========================  =====================================================
Event type                   Data
===========================  =====================================================
``user_message_chunk``       text (the dispatch prompt echo)
``agent_session_started``    session_id, protocol_version
``agent_message_chunk``      text (agent reply deltas)
``agent_thought_chunk``      text (agent reasoning deltas)
``agent_tool_call``          tool_call_id, title, kind, status
``agent_plan``               entries (full plan snapshot)
``agent_plan_update``        plan (items/file/markdown delta, wire names)
``agent_plan_removed``       plan_id
``agent_commands_update``    commands (available-commands list)
``agent_mode_update``        mode_id
``agent_session_info``       title, updated_at
``agent_config_update``      options (config-option list, wire names)
``agent_update``             kind, payload (unrecognized kinds — never dropped)
``agent_usage``              used, size, cost
``agent_permission``         title, action, reason (policy decision)
``agent_finished``           session_id, stop_reason, ok, error (on failure)
===========================  =====================================================

Structured payloads (``entries``, ``plan``, ``commands``, ``options``) are
JSON-safe dumps with the protocol's wire aliases, so event data mirrors the
wire shapes one-to-one.

**Harness trace (``docs/plans/harness-trace-parity.md`` D1/D2/D3/D7):** the agent
is spawned with ``--print-logs --log-level <ACP_HARNESS_LOG_LEVEL>`` so its own
log stream — model calls, loop steps, context/skill loading — arrives on stderr
while stdout stays the JSON-RPC channel, and ``drain_stderr`` surfaces each line
at INFO with a ``[harness]`` label so journald is the single interleaved pane.
Every line is also appended, redacted but otherwise unfiltered, to
``<ACP_TRACE_ROOT>/<run_id>/harness.log`` with a ``manifest.json`` beside it
(``trace_log``): journald rotates in about a day here and the event ring is
volatile, so the run directory is the record. ``ACP_TRACE_ENABLED=false`` drops
the flags, the files and the INFO logging together; nothing else changes.

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
import os
import re
import shutil
import subprocess
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
from webhook_receiver.sandbox_bridge import SandboxBridge, SandboxWorkspace
from webhook_receiver.trace_log import RunTrace, open_run_trace, redact

if TYPE_CHECKING:
    from webhook_receiver.config import Settings
    from webhook_receiver.event_store import EventStore

logger = logging.getLogger(__name__)

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


def _json_safe(obj: Any) -> Any:
    """Best-effort JSON-safe form of a schema object for event payloads.

    Pydantic models dump with their wire aliases (protocol-faithful shapes);
    plain containers recurse; anything else stringifies rather than raising —
    serializing a payload must never break the event stream.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json", by_alias=True)
        except Exception:  # noqa: BLE001 - payload shape is never worth a crash
            pass
    if isinstance(obj, (list, tuple)):
        return [_json_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): _json_safe(value) for key, value in obj.items()}
    return str(obj)


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
        """ALL-traces mapping (webui plan W0): every ``session/update`` kind
        becomes an event; nothing is filtered server-side (the UI filters).
        Unrecognized kinds pass through as ``agent_update`` so future protocol
        additions are visible instead of silently dropped.
        """
        kind = getattr(update, "session_update", type(update).__name__)
        emit = self._store.emit
        run_id = self._run_id
        if kind in ("user_message_chunk", "agent_message_chunk", "agent_thought_chunk"):
            text = getattr(getattr(update, "content", None), "text", None)
            if text:
                emit(kind, run_id=run_id, text=text)
            else:
                # No/empty/non-text content (e.g. an image block): the update
                # still happened, so it passes through rather than dropping.
                emit("agent_update", run_id=run_id, kind=kind, payload=_json_safe(update))
            return
        if kind in ("tool_call", "tool_call_update"):
            emit(
                "agent_tool_call",
                run_id=run_id,
                tool_call_id=getattr(update, "tool_call_id", None),
                title=getattr(update, "title", None),
                kind=getattr(update, "kind", None),
                status=getattr(update, "status", None),
            )
            return
        if kind == "usage_update":
            emit(
                "agent_usage",
                run_id=run_id,
                used=getattr(update, "used", None),
                size=getattr(update, "size", None),
                cost=getattr(update, "cost", None),
            )
            return
        if kind == "plan":
            emit(
                "agent_plan",
                run_id=run_id,
                entries=_json_safe(getattr(update, "entries", None)),
            )
            return
        if kind == "plan_update":
            emit(
                "agent_plan_update",
                run_id=run_id,
                plan=_json_safe(getattr(update, "plan", None)),
            )
            return
        if kind == "plan_removed":
            emit(
                "agent_plan_removed",
                run_id=run_id,
                plan_id=getattr(update, "plan_id", None),
            )
            return
        if kind == "available_commands_update":
            emit(
                "agent_commands_update",
                run_id=run_id,
                commands=_json_safe(getattr(update, "available_commands", None)),
            )
            return
        if kind == "current_mode_update":
            emit(
                "agent_mode_update",
                run_id=run_id,
                mode_id=getattr(update, "current_mode_id", None),
            )
            return
        if kind == "session_info_update":
            emit(
                "agent_session_info",
                run_id=run_id,
                title=getattr(update, "title", None),
                updated_at=getattr(update, "updated_at", None),
            )
            return
        if kind == "config_option_update":
            emit(
                "agent_config_update",
                run_id=run_id,
                options=_json_safe(getattr(update, "config_options", None)),
            )
            return
        emit("agent_update", run_id=run_id, kind=kind, payload=_json_safe(update))

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
    """Runs one cold ACP session per :class:`PromptInfo` envelope.

    Phase 4: when the settings enable it (``SANDBOX_ENABLED``), the session
    cwd is a SwarmSandbox-materialized workspace (bridge ``prepare`` /
    ``release`` around the session, Decision 5); ``ACP_CLONE_ROOT`` maps the
    envelope onto an existing checkout of its repo; the default is the
    Phase 2 plain scratch dir. The two environment knobs are mutually
    exclusive (dual agent environments,
    ``docs/plans/dispatch-in-live-checkout.md``) — setting both fails at
    construction instead of letting the bridge silently shadow the clone.
    A bridge may be injected (tests); injection counts as the sandbox
    environment too, so it fails with ``ACP_CLONE_ROOT`` just the same.
    Without injection one is built from settings when enabled.
    """

    def __init__(
        self,
        settings: Settings,
        store: EventStore,
        bridge: SandboxBridge | None = None,
    ) -> None:
        if settings.acp_clone_root and (settings.sandbox_enabled or bridge is not None):
            raise AcpHostError(
                "SANDBOX_ENABLED (or an injected sandbox bridge) and "
                "ACP_CLONE_ROOT are mutually exclusive "
                "(dual agent environments, docs/plans/dispatch-in-live-checkout.md): "
                "the sandbox bridge would silently shadow the clone checkout"
            )
        self._settings = settings
        self._store = store
        self._bridge = (
            bridge
            if bridge is not None
            else (SandboxBridge(settings, store) if settings.sandbox_enabled else None)
        )

    async def run(self, info: PromptInfo) -> AcpRunResult:
        """Drive one prompt end-to-end; raises :class:`AcpHostError` on failure."""
        bin_path = resolve_opencode_bin(self._settings)
        sandbox: SandboxWorkspace | None = None
        if self._bridge is not None:
            try:
                sandbox = await self._bridge.prepare(info)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Fail closed (no scratch-dir fallback): an enabled-but-broken
                # sandbox surfaces as a failed run (prompt_consumed {ok:false}).
                raise AcpHostError(
                    f"sandbox workspace failed for delivery {info.delivery_id}: {exc}"
                ) from exc
            workspace = sandbox.path
        else:
            workspace = await self._prepare_workspace(info)
        self._write_deny_config(workspace, delivery_id=info.delivery_id)
        client = HostClient(self._settings, self._store, run_id=info.id)
        step = self._settings.acp_step_timeout
        prompt_timeout = self._settings.acp_prompt_timeout
        trace_enabled = self._settings.acp_trace_enabled
        trace: RunTrace | None = (
            open_run_trace(
                self._settings.acp_trace_root,
                self._settings.acp_trace_keep_runs,
                info,
                workspace,
            )
            if trace_enabled
            else None
        )
        response: Any = None
        session_id: str | None = None
        conn: Any = None
        proc: Any = None
        drainer: asyncio.Task[None] | None = None

        async def drain_stderr() -> None:
            stream = proc.stderr if proc is not None else None
            if stream is None:
                return
            # The harness's own log stream (opencode ``--print-logs`` writes to
            # stderr) is the detail the event contract does not carry, so it is
            # surfaced at INFO — journald is the single pane (D1/D2) — and every
            # line is also appended to the run's ``harness.log``, redacted but
            # otherwise unfiltered (D3: the file is the record, the pane is the
            # readable view). With trace capture off it stays a DEBUG drain:
            # read so the pipe never blocks, not published.
            log = logger.info if trace_enabled else logger.debug
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = redact(line.decode(errors="replace").rstrip())
                if trace is not None:
                    trace.write(text)
                log("[harness] run_id=%s: %s", info.id, text)

        try:
            # opencode >= 2.0 rejects `--cwd` outright — the workspace rides
            # the process cwd (and session/new below).
            agent_args = ["acp"]
            if trace_enabled:
                agent_args += [
                    "--print-logs",
                    "--log-level",
                    self._settings.acp_harness_log_level.lower(),
                ]
            async with asyncio.timeout(step * 3 + prompt_timeout):
                async with spawn_agent_process(
                    client,
                    bin_path,
                    *agent_args,
                    # The SDK's spawner trims the environment to an MCP-safe
                    # subset (no GITHUB_TOKEN / provider keys) unless the env
                    # is passed explicitly — sessions would run credential-less.
                    # OS_WEBHOOK_SECRET stays receiver-side: the agent has no
                    # use for the webhook signing secret.
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k != "OS_WEBHOOK_SECRET"
                    },
                    cwd=str(workspace),
                ) as (conn, proc):
                    drainer = asyncio.create_task(drain_stderr())
                    init = await asyncio.wait_for(
                        conn.initialize(
                            PROTOCOL_VERSION,
                            client_capabilities=ClientCapabilities(),
                            client_info=Implementation(
                                name="swarm-orchestration-host", version="0.2.0"
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
            if trace is not None:
                trace.finish(ok=False, error=error, session_id=session_id)
            raise AcpHostError(f"acp session failed for delivery {info.delivery_id}: {error}") from exc
        finally:
            if drainer is not None and not drainer.done():
                drainer.cancel()
                await asyncio.gather(drainer, return_exceptions=True)
            if trace is not None:
                # Closed after the drainer so no line is written to a closed
                # handle. A shutdown cancel leaves the manifest without
                # ``ended_at`` — that absence is the record of an abandoned run.
                trace.close()
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
            if sandbox is not None and self._bridge is not None:
                # Shielded so a shutdown cancel cannot strand the release
                # mid-await; the reaper TTL is the crash backstop regardless.
                try:
                    await asyncio.shield(self._bridge.release(sandbox))
                except Exception:
                    logger.warning(
                        "sandbox release failed run_id=%s sandbox_id=%s",
                        info.id,
                        sandbox.sandbox_id,
                    )

        stop_reason = getattr(response, "stop_reason", None)
        self._store.emit(
            "agent_finished",
            run_id=info.id,
            session_id=session_id,
            stop_reason=stop_reason,
            ok=True,
        )
        if trace is not None:
            trace.finish(
                ok=True, stop_reason=stop_reason or "", session_id=session_id
            )
        return AcpRunResult(
            session_id=session_id or "",
            stop_reason=stop_reason or "",
            workspace=str(workspace),
        )

    async def _prepare_workspace(self, info: PromptInfo) -> Path:
        """Session cwd for the agent; a scratch dir is never the service's
        own repo — ``ACP_CLONE_ROOT`` deliberately maps onto the launcher's
        real checkout of the envelope's repo instead.

        ``ACP_CLONE_ROOT`` maps the envelope's repo onto an existing
        checkout of it (the launcher-minted clone) — the old-topology
        behavior where the agent works in the real repo. The checkout is
        resolved by repo *name* under the root, then verified against the
        envelope: the name segment must be a plain path component (never
        ``.``/``..``), and the checkout's ``origin`` must point at the
        envelope's repo, so a same-named checkout of a different owner's
        repo never receives the session. Missing checkout or a mismatch
        fails the envelope (no scratch fallback: the direct-body prompt is
        meaningless outside the repo it targets). Unset → scratch dir.
        """
        if self._settings.acp_clone_root:
            name = info.repo.rsplit("/", 1)[-1]
            if name in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise AcpHostError(
                    f"invalid repo name for clone-root resolution, delivery "
                    f"{info.delivery_id}: {info.repo!r}"
                )
            workspace = Path(self._settings.acp_clone_root).expanduser() / name
            # A worktree's .git is a file (gitdir: pointer), not a dir.
            if not (workspace / ".git").exists():
                raise AcpHostError(
                    f"clone checkout not found for delivery {info.delivery_id}: "
                    f"{workspace} (ACP_CLONE_ROOT set — create/clone the repo, "
                    "or unset the knob for scratch workspaces)"
                )
            if not await self._checkout_is_repo(workspace, info.repo):
                raise AcpHostError(
                    f"clone checkout identity mismatch for delivery "
                    f"{info.delivery_id}: {workspace} is not a checkout of "
                    f"{info.repo}"
                )
            return workspace
        root = (
            Path(self._settings.acp_workspace_root).expanduser()
            if self._settings.acp_workspace_root
            else Path("/tmp") / "swarm-acp-workspaces"
        )
        workspace = root / info.id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    @staticmethod
    async def _checkout_is_repo(workspace: Path, repo: str) -> bool:
        """True when the checkout's ``origin`` points at ``owner/repo``.

        Accepts the ssh (``git@host:owner/repo.git``) and https
        (``https://host/owner/repo.git[/]``) URL forms; anything unreadable
        or pointing elsewhere is a mismatch (fail closed).

        The probe runs in a worker thread: ``run()`` executes directly on
        the event loop, so a synchronous ``subprocess.run`` would stall
        webhook handling and queue draining for up to its timeout.
        """
        try:
            res = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", str(workspace), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except Exception:
            return False
        match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", res.stdout.strip())
        return bool(match) and match.group(1).lower() == repo.lower()

    def _write_deny_config(self, workspace: Path, delivery_id: str) -> None:
        """Belt-and-braces deny-list, applied to bare workspaces only.

        A lived-in checkout is never written into: ``ACP_CLONE_ROOT``
        workspaces are skipped outright (an untracked ``opencode.json``
        would dirty the checkout's git status; the guarantee there is the
        checkout's own permission posture — launcher-seeded config, else
        the runtime policy's ``ACP_DEFAULT_PERMISSION``). Any workspace
        already managing an opencode config (e.g. a sandbox workspace
        materialized from a repo that ships one) is skipped too, so the
        file never fights it. Both skips leave ``ACP_DENIED_TOOLS``
        unenforced at the config layer — say so, since the runtime policy
        never consults that knob.
        """
        if not self._settings.acp_denied_tools:
            return
        if self._settings.acp_clone_root:
            logger.warning(
                "ACP_DENIED_TOOLS not applied for delivery %s: clone-root "
                "checkout is never written into (runtime permission policy "
                "is the enforcement there)",
                delivery_id,
            )
            return  # lived-in checkout: the host never mutates it
        manages_own_config = any(
            (workspace / name).exists()
            for name in (".opencode", "opencode.json", "opencode.jsonc")
        )
        if manages_own_config:
            logger.warning(
                "ACP_DENIED_TOOLS not applied for delivery %s: workspace "
                "manages its own opencode config",
                delivery_id,
            )
            return
        config = {
            "$schema": "https://opencode.ai/config.json",
            "permission": {tool: "deny" for tool in self._settings.acp_denied_tools},
        }
        (workspace / "opencode.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
