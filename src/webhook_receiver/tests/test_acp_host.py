"""Tests for the ACP host (webhook_receiver.acp_host) — mock-based, no real
opencode: the spawn point is monkeypatched with a canned connection.

Sync tests driving the async host via ``asyncio.run`` (suite convention —
no pytest-asyncio dependency)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from acp.schema import (
    AgentMessageChunk,
    PermissionOption,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
)

import webhook_receiver.acp_host as acp_host_module
from webhook_receiver.acp_host import (
    AcpHost,
    AcpHostError,
    AcpRunResult,
    HostClient,
    build_prompt,
    resolve_opencode_bin,
)
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.prompt_queue import PromptInfo

VALID_PAYLOAD = {
    "action": "labeled",
    "repository": {"full_name": "owner/repo"},
}


def make_settings(tmp_path: Path, **acp: object) -> Settings:
    return Settings(
        host="testserver",
        port=80,
        github_webhook_secret="FAKE-WEBHOOK-SECRET-FOR-TESTING",
        max_body_bytes=25 * 1024 * 1024,
        log_level="info",
        acp_workspace_root=str(tmp_path / "ws"),
        acp_step_timeout=1.0,
        acp_prompt_timeout=1.0,
        **acp,
    )


def make_info(**overrides: object) -> PromptInfo:
    fields: dict[str, object] = {
        "delivery_id": "d-1",
        "repo": "owner/repo",
        "event": "issues",
        "action": "labeled",
        "label": "orchestration:plan",
        "payload": dict(VALID_PAYLOAD),
    }
    fields.update(overrides)
    return PromptInfo(**fields)  # type: ignore[arg-type]


class FakeProc:
    """Mimics the asyncio subprocess surface the host touches.

    ``stderr_text`` is materialized into a real StreamReader when the fake
    spawn enters its (running) event loop — constructing a StreamReader
    outside a loop binds to the deprecated global loop and breaks under
    ``asyncio.run``.
    """

    def __init__(self, stderr_text: str | None = None) -> None:
        self.returncode: int | None = None
        self.killed = False
        self._stderr_text = stderr_text
        self.stderr: asyncio.StreamReader | None = None

    def materialize_stderr(self) -> None:
        if self._stderr_text is not None and self.stderr is None:
            reader = asyncio.StreamReader()
            reader.feed_data(self._stderr_text.encode())
            reader.feed_eof()
            self.stderr = reader

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


class FakeConn:
    """Canned ACP connection: initialize/new_session/prompt + updates."""

    def __init__(
        self,
        stop_reason: str = "end_turn",
        prompt_exc: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.client: object | None = None
        self.stop_reason = stop_reason
        self.prompt_exc = prompt_exc
        self.delay = delay
        self.calls: list[tuple] = []
        self.prompt_texts: list[str] = []

    async def initialize(self, protocol_version: int, **_: object):
        self.calls.append(("initialize", protocol_version))
        # Yield once so scheduled tasks (stderr drainer) get a loop turn,
        # like real I/O would.
        await asyncio.sleep(0)
        return SimpleNamespace(protocol_version=protocol_version)

    async def new_session(self, cwd: str, **_: object):
        self.calls.append(("new_session", cwd))
        return SimpleNamespace(session_id="sess-1")

    async def prompt(self, session_id: str, prompt: list, **_: object):
        self.calls.append(("prompt", session_id))
        self.prompt_texts = [b.text for b in prompt]
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.prompt_exc is not None:
            raise self.prompt_exc
        # Real SDK: session/update notifications drain before prompt returns.
        if self.client is not None:
            await self.client.session_update(
                session_id,
                AgentMessageChunk(
                    session_update="agent_message_chunk",
                    content=TextContentBlock(type="text", text="ACP-OK"),
                ),
            )
            await self.client.session_update(
                session_id,
                ToolCallStart(
                    session_update="tool_call",
                    tool_call_id="tc-1",
                    kind="read",
                    status="pending",
                    title="read x",
                ),
            )
            await self.client.session_update(
                session_id,
                ToolCallProgress(
                    session_update="tool_call_update",
                    tool_call_id="tc-1",
                    kind="read",
                    status="completed",
                    title="read x",
                ),
            )
            await self.client.session_update(
                session_id, UsageUpdate(session_update="usage_update", used=5, size=1000)
            )
        return SimpleNamespace(stop_reason=self.stop_reason)


def install_spawn(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    proc: FakeProc,
    calls: list,
) -> None:
    @contextlib.asynccontextmanager
    async def fake_spawn(client: object, command: str, *args: str):
        calls.append((client, command, args))
        conn.client = client
        proc.materialize_stderr()  # bind the reader to the running loop
        try:
            yield conn, proc
        except BaseException:
            # Body raised (e.g. timeout): leave returncode unset so the
            # host's own kill-on-exit path is exercised.
            raise
        else:
            # The real context manager terminates the agent on clean exit.
            proc.returncode = proc.returncode or 0

    monkeypatch.setattr(acp_host_module, "spawn_agent_process", fake_spawn)


def events_of_type(store: EventStore, type_: str) -> list[dict]:
    return [e for e in store.recent() if e["type"] == type_]


class TestRunHappyPath:
    def test_streams_events_and_returns_result(self, tmp_path, monkeypatch) -> None:
        store = EventStore()
        cfg = make_settings(tmp_path)
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)
        info = make_info()

        result = asyncio.run(AcpHost(cfg, store).run(info))

        assert isinstance(result, AcpRunResult)
        assert result.session_id == "sess-1"
        assert result.stop_reason == "end_turn"
        assert str(tmp_path / "ws" / info.id) == result.workspace

        kinds = [e["type"] for e in store.recent()]
        assert kinds == [
            "agent_session_started",
            "agent_message_chunk",
            "agent_tool_call",
            "agent_tool_call",
            "agent_usage",
            "agent_finished",
        ]
        started = events_of_type(store, "agent_session_started")[0]["data"]
        assert started["run_id"] == info.id
        assert started["session_id"] == "sess-1"
        assert started["protocol_version"] == 1
        assert events_of_type(store, "agent_message_chunk")[0]["data"]["text"] == "ACP-OK"
        tool_calls = events_of_type(store, "agent_tool_call")
        assert [tc["data"]["status"] for tc in tool_calls] == ["pending", "completed"]
        assert tool_calls[0]["data"]["run_id"] == info.id
        assert events_of_type(store, "agent_usage")[0]["data"]["used"] == 5
        finished = events_of_type(store, "agent_finished")[0]["data"]
        assert finished == {
            "run_id": info.id,
            "session_id": "sess-1",
            "stop_reason": "end_turn",
            "ok": True,
        }

    def test_spawns_opencode_acp_in_workspace(self, tmp_path, monkeypatch) -> None:
        cfg = make_settings(tmp_path, acp_opencode_bin="/bin/opencode-fake")
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        (client, command, args) = calls[0]
        assert isinstance(client, HostClient)
        assert command == "/bin/opencode-fake"
        assert args[0] == "acp"
        assert args[1] == "--cwd"
        assert Path(args[2]).is_dir()
        # new_session received the same workspace cwd
        assert conn.calls[1][1] == args[2]

    def test_prompt_derived_from_envelope(self, tmp_path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        text = conn.prompt_texts[0]
        assert "owner/repo" in text
        assert "orchestration:plan" in text
        assert "d-1" in text

    def test_envelope_prompt_wins_when_present(self, tmp_path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        asyncio.run(AcpHost(cfg, EventStore()).run(make_info(prompt="custom prompt body")))

        assert conn.prompt_texts == ["custom prompt body"]

    def test_workspace_deny_config_written(self, tmp_path, monkeypatch) -> None:
        cfg = make_settings(tmp_path, acp_denied_tools=("bash", "write"))
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        config_path = Path(conn.calls[1][1]) / "opencode.json"
        config = json.loads(config_path.read_text())
        assert config["permission"] == {"bash": "deny", "write": "deny"}

    def test_workspace_without_denied_tools_has_no_config(
        self, tmp_path, monkeypatch
    ) -> None:
        cfg = make_settings(tmp_path)
        conn, proc, calls = FakeConn(), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        assert not (Path(conn.calls[1][1]) / "opencode.json").exists()

    def test_stderr_drained_with_redaction(self, tmp_path, monkeypatch, caplog) -> None:
        cfg = make_settings(tmp_path)
        conn = FakeConn()
        proc = FakeProc(stderr_text="connecting token=supersecret ok\n")
        calls: list = []
        install_spawn(monkeypatch, conn, proc, calls)

        with caplog.at_level("DEBUG", logger="webhook_receiver.acp_host"):
            asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        assert "supersecret" not in caplog.text
        assert "token=<redacted>" in caplog.text

    def test_non_end_turn_stop_reason_still_succeeds(self, tmp_path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        conn, proc, calls = FakeConn(stop_reason="refusal"), FakeProc(), []
        install_spawn(monkeypatch, conn, proc, calls)

        result = asyncio.run(AcpHost(cfg, EventStore()).run(make_info()))

        assert result.stop_reason == "refusal"


class TestRunFailures:
    def test_prompt_exception_raises_and_emits_failed_finished(
        self, tmp_path, monkeypatch
    ) -> None:
        store = EventStore()
        cfg = make_settings(tmp_path)
        conn = FakeConn(prompt_exc=RuntimeError("boom"))
        install_spawn(monkeypatch, conn, FakeProc(), [])

        with pytest.raises(AcpHostError, match="boom"):
            asyncio.run(AcpHost(cfg, store).run(make_info()))

        finished = events_of_type(store, "agent_finished")[0]["data"]
        assert finished["ok"] is False
        assert "boom" in finished["error"]
        assert finished["stop_reason"] is None

    def test_prompt_timeout_raises_acp_host_error(self, tmp_path, monkeypatch) -> None:
        store = EventStore()
        cfg = make_settings(tmp_path)
        conn = FakeConn(delay=5.0)
        proc = FakeProc()
        install_spawn(monkeypatch, conn, proc, [])

        with pytest.raises(AcpHostError, match="timed out"):
            asyncio.run(AcpHost(cfg, store).run(make_info()))

        assert events_of_type(store, "agent_finished")[0]["data"]["ok"] is False
        # Orphan hygiene: the stuck process was killed despite the fake
        # context manager's clean-exit simulation.
        assert proc.killed is True

    def test_spawn_failure_raises_acp_host_error(self, tmp_path, monkeypatch) -> None:
        store = EventStore()
        cfg = make_settings(tmp_path)

        @contextlib.asynccontextmanager
        async def failing_spawn(client: object, command: str, *args: str):
            raise AcpHostError("cannot spawn")
            yield  # pragma: no cover

        monkeypatch.setattr(acp_host_module, "spawn_agent_process", failing_spawn)

        with pytest.raises(AcpHostError, match="cannot spawn"):
            asyncio.run(AcpHost(cfg, store).run(make_info()))

        finished = events_of_type(store, "agent_finished")
        assert finished[0]["data"]["ok"] is False

    def test_unexpected_session_id_missing_still_reports(self, tmp_path, monkeypatch) -> None:
        # Failure before new_session: agent_finished carries no session id.
        store = EventStore()
        cfg = make_settings(tmp_path)

        conn = FakeConn()

        async def failing_initialize(protocol_version: int, **_: object):
            raise RuntimeError("init refused")

        conn.initialize = failing_initialize  # type: ignore[method-assign]
        install_spawn(monkeypatch, conn, FakeProc(), [])

        with pytest.raises(AcpHostError, match="init refused"):
            asyncio.run(AcpHost(cfg, store).run(make_info()))

        finished = events_of_type(store, "agent_finished")[0]["data"]
        assert finished["session_id"] is None
        assert finished["ok"] is False


class TestResolveOpencodeBin:
    def test_explicit_setting_wins(self, tmp_path: Path) -> None:
        cfg = make_settings(tmp_path, acp_opencode_bin="/opt/oc")
        assert resolve_opencode_bin(cfg) == "/opt/oc"

    def test_path_lookup_second(self, tmp_path: Path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        monkeypatch.setattr(acp_host_module.shutil, "which", lambda name: "/usr/bin/oc")
        assert resolve_opencode_bin(cfg) == "/usr/bin/oc"

    def test_home_default_third(self, tmp_path: Path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        monkeypatch.setattr(acp_host_module.shutil, "which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".opencode" / "bin").mkdir(parents=True)
        (tmp_path / ".opencode" / "bin" / "opencode").write_text("#!/bin/sh\n")
        assert resolve_opencode_bin(cfg) == str(tmp_path / ".opencode" / "bin" / "opencode")

    def test_missing_binary_raises(self, tmp_path: Path, monkeypatch) -> None:
        cfg = make_settings(tmp_path)
        monkeypatch.setattr(acp_host_module.shutil, "which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "nonexistent-home"))
        with pytest.raises(AcpHostError, match="opencode binary not found"):
            resolve_opencode_bin(cfg)


class TestBuildPrompt:
    def test_derived_prompt_names_repo_event_label(self) -> None:
        text = build_prompt(make_info())
        assert "owner/repo" in text
        assert "issues" in text
        assert "labeled" in text
        assert "orchestration:plan" in text

    def test_envelope_prompt_preferred(self) -> None:
        assert build_prompt(make_info(prompt="p")) == "p"


class TestHostClientMapping:
    """session_update kinds -> EventStore contract (module docstring table)."""

    def make_client(self) -> tuple[HostClient, EventStore]:
        store = EventStore()
        return HostClient(make_settings(Path("/tmp")), store, run_id="run-1"), store

    def test_message_chunk_without_text_ignored(self) -> None:
        client, store = self.make_client()

        async def main() -> None:
            await client.session_update(
                "s",
                SimpleNamespace(session_update="agent_message_chunk", content=SimpleNamespace()),
            )

        asyncio.run(main())
        assert store.recent() == []

    def test_unmapped_kinds_ignored(self) -> None:
        client, store = self.make_client()

        async def main() -> None:
            for kind in ("plan", "available_commands_update", "current_mode_update"):
                await client.session_update("s", SimpleNamespace(session_update=kind))

        asyncio.run(main())
        assert store.recent() == []

    def test_request_permission_applies_policy_and_emits(self) -> None:
        client, store = self.make_client()
        tool_call = ToolCallStart(
            session_update="tool_call",
            tool_call_id="tc-9",
            kind="read",
            status="pending",
            title="read notes.md",
        )
        options = [
            PermissionOption(option_id="allow", name="Allow", kind="allow_always"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
        ]

        response = asyncio.run(client.request_permission("s", tool_call, options))

        assert response.outcome.option_id == "allow"
        emitted = events_of_type(store, "agent_permission")[0]["data"]
        assert emitted["run_id"] == "run-1"
        assert emitted["title"] == "read notes.md"
        assert emitted["action"] == "allow_always"

    def test_request_permission_deny_pattern_rejects(self) -> None:
        store = EventStore()
        cfg = make_settings(Path("/tmp"), acp_deny_patterns=("rm\\s+-rf",))
        client = HostClient(cfg, store, run_id="run-1")
        tool_call = ToolCallStart(
            session_update="tool_call",
            tool_call_id="tc-9",
            kind="execute",
            status="pending",
            title="bash",
            raw_input={"command": "rm -rf /"},
        )
        options = [
            PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
            PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
        ]

        response = asyncio.run(client.request_permission("s", tool_call, options))

        assert response.outcome.option_id == "reject"
        emitted = events_of_type(store, "agent_permission")[0]["data"]
        assert emitted["action"] == "reject"
        assert "deny pattern" in emitted["reason"]
