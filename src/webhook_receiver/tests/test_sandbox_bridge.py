"""Tests for the SwarmSandbox bridge (webhook_receiver.sandbox_bridge) and
its AcpHost wiring — mock-based, no real sandbox API, Docker, or opencode:
HTTP is faked with ``httpx.MockTransport`` and the docker/git subprocess
seams are monkeypatched (CI has none of the real targets).

Sync tests driving the async bridge via ``asyncio.run`` (suite convention —
no pytest-asyncio dependency)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import webhook_receiver.acp_host as acp_host_module
import webhook_receiver.sandbox_bridge as bridge_module
from webhook_receiver.acp_host import AcpHost, AcpHostError
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.prompt_queue import PromptInfo
from webhook_receiver.sandbox_bridge import (
    SandboxBridge,
    SandboxBridgeError,
    SandboxWorkspace,
)

VALID_PAYLOAD = {
    "action": "labeled",
    "repository": {"full_name": "owner/repo"},
}


def make_settings(tmp_path: Path, **extra: object) -> Settings:
    params: dict[str, object] = {
        "host": "testserver",
        "port": 80,
        "github_webhook_secret": "FAKE-WEBHOOK-SECRET-FOR-TESTING",
        "max_body_bytes": 25 * 1024 * 1024,
        "log_level": "info",
        "acp_workspace_root": str(tmp_path / "ws"),
        "acp_step_timeout": 1.0,
        "acp_prompt_timeout": 1.0,
        "acp_opencode_bin": "opencode-test-stub",
        "sandbox_enabled": True,
        "sandbox_api_url": "http://sandbox.test",
        "sandbox_ready_timeout": 5.0,
    }
    params.update(extra)
    return Settings(**params)  # type: ignore[arg-type]


def make_envelope() -> PromptInfo:
    return PromptInfo(
        delivery_id="d-1",
        repo="owner/repo",
        event="issues",
        action="labeled",
        label="orchestration:plan-approved",
        payload=dict(VALID_PAYLOAD),
    )


def api_transport(
    create_status: int = 202,
    delete_status: int = 204,
    calls: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Sandbox API fake: POST /api/sandboxes -> 202, DELETE /api/sandboxes/sbx-1."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.method == "POST" and request.url.path == "/api/sandboxes":
            body = json.loads(request.content)
            return httpx.Response(
                create_status,
                json={
                    "sandboxId": "sbx-1",
                    "branch": body.get("branch", "development"),
                    "containerName": "swarmsandbox-deadbeef",
                },
            )
        if request.method == "DELETE" and request.url.path == "/api/sandboxes/sbx-1":
            return httpx.Response(delete_status)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    return httpx.MockTransport(handler)


def fake_docker_cp_populates(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, Path]]:
    """Stub _docker_cp: the first copy lands nothing, later copies materialize
    the clone markers (as if the in-container entrypoint clone just finished)."""

    calls: list[tuple[str, Path]] = []

    async def _cp(docker_bin: str, container: str, dest: Path) -> None:
        calls.append((container, dest))
        dest.mkdir(parents=True, exist_ok=True)
        if len(calls) > 1:
            (dest / ".git").mkdir(exist_ok=True)
            skill = dest / ".agents" / "skills" / "swarm"
            skill.mkdir(parents=True, exist_ok=True)
            (skill / "SKILL.md").write_text("swarm", encoding="utf-8")

    monkeypatch.setattr(bridge_module, "_docker_cp", _cp)
    return calls


def events_of_type(store: EventStore, type_: str) -> list[dict]:
    return [e for e in store.recent() if e["type"] == type_]


def fake_remove_origin(
    monkeypatch: pytest.MonkeyPatch, removed: list[Path] | None = None
) -> list[Path]:
    """Stub _remove_origin (async in production); records workspace paths."""

    seen: list[Path] = removed if removed is not None else []

    async def _remove(workspace: Path) -> None:
        seen.append(Path(workspace))

    monkeypatch.setattr(bridge_module, "_remove_origin", _remove)
    return seen


class FakeProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stderr = None  # drain_stderr returns early on a null stream

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


class FakeConn:
    def __init__(self, prompt_delay: float = 0.0) -> None:
        self.client: object | None = None
        self.prompt_delay = prompt_delay
        self.new_session_kwargs: dict = {}

    async def initialize(self, protocol_version: int, **_: object):
        await asyncio.sleep(0)
        return SimpleNamespace(protocol_version=protocol_version)

    async def new_session(self, **kwargs: object):
        self.new_session_kwargs = kwargs
        return SimpleNamespace(session_id="sess-1")

    async def prompt(self, *a: object, **k: object):
        if self.prompt_delay:
            await asyncio.sleep(self.prompt_delay)
        return SimpleNamespace(stop_reason="end_turn")


def install_spawn(
    monkeypatch: pytest.MonkeyPatch, conn: FakeConn, proc: FakeProc
) -> None:
    @contextlib.asynccontextmanager
    async def fake_spawn(client: object, command: str, *args: str):
        conn.client = client
        try:
            yield conn, proc
        finally:
            proc.returncode = proc.returncode or 0

    monkeypatch.setattr(acp_host_module, "spawn_agent_process", fake_spawn)


class TestSettingsParsing:
    def test_dataclass_defaults_disabled(self) -> None:
        settings = Settings(
            host="h", port=1, github_webhook_secret="s",
            max_body_bytes=1, log_level="info",
        )
        assert settings.sandbox_enabled is False
        assert settings.sandbox_api_url == ""
        assert settings.sandbox_branch == "development"
        assert settings.sandbox_ready_timeout == 300.0
        assert settings.sandbox_docker_bin == "docker"

    def test_from_env_parses_all_knobs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "s")
        monkeypatch.setenv("SANDBOX_ENABLED", "true")
        monkeypatch.setenv("SANDBOX_API_URL", "http://sbx:5000/")
        monkeypatch.setenv("SANDBOX_BRANCH", "dev/phase4")
        monkeypatch.setenv("SANDBOX_READY_TIMEOUT", "42")
        monkeypatch.setenv("SANDBOX_DOCKER_BIN", "/usr/bin/docker")
        settings = Settings.from_env()
        assert settings.sandbox_enabled is True
        assert settings.sandbox_api_url == "http://sbx:5000/"
        assert settings.sandbox_branch == "dev/phase4"
        assert settings.sandbox_ready_timeout == 42.0
        assert settings.sandbox_docker_bin == "/usr/bin/docker"

    def test_enabled_without_api_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "s")
        monkeypatch.setenv("SANDBOX_ENABLED", "1")
        monkeypatch.delenv("SANDBOX_API_URL", raising=False)
        with pytest.raises(ValueError, match="SANDBOX_API_URL is required"):
            Settings.from_env()

    def test_disabled_without_api_url_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "s")
        monkeypatch.delenv("SANDBOX_API_URL", raising=False)
        assert Settings.from_env().sandbox_enabled is False


class TestPrepare:
    def test_provisions_and_materializes_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)
        requests: list[httpx.Request] = []
        bridge = SandboxBridge(
            settings, EventStore(), transport=api_transport(calls=requests)
        )
        cp_calls = fake_docker_cp_populates(monkeypatch)
        removed = fake_remove_origin(monkeypatch)
        info = make_envelope()

        workspace = asyncio.run(bridge.prepare(info))

        assert workspace.run_id == info.id
        assert workspace.sandbox_id == "sbx-1"
        assert workspace.container_name == "swarmsandbox-deadbeef"
        assert (workspace.path / ".git").is_dir()
        assert removed == [workspace.path]
        # Create used the configured branch; cp targeted the container workspace.
        assert json.loads(requests[0].content) == {"branch": "development"}
        assert cp_calls[0][0] == "swarmsandbox-deadbeef"
        assert cp_calls[0][1] == workspace.path

    def test_workspace_path_is_per_envelope_under_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)
        bridge = SandboxBridge(settings, EventStore(), transport=api_transport())
        fake_docker_cp_populates(monkeypatch)
        fake_remove_origin(monkeypatch)
        info = make_envelope()

        workspace = asyncio.run(bridge.prepare(info))

        assert workspace.path == Path(str(settings.acp_workspace_root)) / info.id

    def test_emits_sandbox_provisioned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)
        store = EventStore()
        bridge = SandboxBridge(settings, store, transport=api_transport())
        fake_docker_cp_populates(monkeypatch)
        fake_remove_origin(monkeypatch)

        workspace = asyncio.run(bridge.prepare(make_envelope()))

        (event,) = events_of_type(store, "sandbox_provisioned")
        assert event["data"]["run_id"] == workspace.run_id
        assert event["data"]["sandbox_id"] == "sbx-1"
        assert event["data"]["container_name"] == "swarmsandbox-deadbeef"
        assert event["data"]["workspace"] == str(workspace.path)

    def test_polls_until_assets_appear(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)
        bridge = SandboxBridge(settings, EventStore(), transport=api_transport())
        cp_calls = fake_docker_cp_populates(monkeypatch)
        fake_remove_origin(monkeypatch)
        monkeypatch.setattr(bridge_module, "_POLL_INTERVAL_SECONDS", 0.01)

        asyncio.run(bridge.prepare(make_envelope()))

        assert len(cp_calls) == 2  # first cp: clone not landed yet; second: ready

    def test_timeout_when_clone_never_lands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path, sandbox_ready_timeout=0.05)
        bridge = SandboxBridge(settings, EventStore(), transport=api_transport())

        async def _cp(docker_bin: str, container: str, dest: Path) -> None:
            dest.mkdir(parents=True, exist_ok=True)  # empty workspace forever

        monkeypatch.setattr(bridge_module, "_docker_cp", _cp)
        monkeypatch.setattr(bridge_module, "_POLL_INTERVAL_SECONDS", 0.01)

        with pytest.raises(SandboxBridgeError, match="did not materialize"):
            asyncio.run(bridge.prepare(make_envelope()))

    def test_create_failure_raises(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path)
        bridge = SandboxBridge(
            settings, EventStore(), transport=api_transport(create_status=502)
        )
        with pytest.raises(SandboxBridgeError, match="sandbox API"):
            asyncio.run(bridge.prepare(make_envelope()))

    def test_create_bad_body_raises(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path)
        transport = httpx.MockTransport(
            lambda request: httpx.Response(202, json={"unexpected": True})
        )
        bridge = SandboxBridge(settings, EventStore(), transport=transport)
        with pytest.raises(SandboxBridgeError, match="sandboxId"):
            asyncio.run(bridge.prepare(make_envelope()))

    def test_unreachable_api_fails_closed(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, sandbox_api_url="http://127.0.0.1:1")
        bridge = SandboxBridge(settings, EventStore())
        with pytest.raises(SandboxBridgeError, match="sandbox API"):
            asyncio.run(bridge.prepare(make_envelope()))

    def test_materialize_failure_releases_the_sandbox(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = make_settings(tmp_path)
        requests: list[httpx.Request] = []
        bridge = SandboxBridge(
            settings, EventStore(), transport=api_transport(calls=requests)
        )

        async def _cp(docker_bin: str, container: str, dest: Path) -> None:
            raise SandboxBridgeError("docker cp failed: container gone")

        monkeypatch.setattr(bridge_module, "_docker_cp", _cp)
        with pytest.raises(SandboxBridgeError, match="docker cp failed"):
            asyncio.run(bridge.prepare(make_envelope()))
        deletes = [r for r in requests if r.method == "DELETE"]
        assert [str(r.url) for r in deletes] == [
            "http://sandbox.test/api/sandboxes/sbx-1"
        ]


class TestRelease:
    def make_workspace(self, tmp_path: Path) -> SandboxWorkspace:
        return SandboxWorkspace(
            run_id="run-1",
            sandbox_id="sbx-1",
            container_name="c",
            path=tmp_path / "ws" / "run-1",
        )

    def test_delete_204_emits_released_ok(self, tmp_path: Path) -> None:
        store = EventStore()
        bridge = SandboxBridge(
            make_settings(tmp_path), store, transport=api_transport()
        )
        asyncio.run(bridge.release(self.make_workspace(tmp_path)))
        (event,) = events_of_type(store, "sandbox_released")
        assert event["data"] == {
            "run_id": "run-1",
            "sandbox_id": "sbx-1",
            "ok": True,
        }

    def test_delete_404_counts_as_released(self, tmp_path: Path) -> None:
        store = EventStore()
        bridge = SandboxBridge(
            make_settings(tmp_path), store, transport=api_transport(delete_status=404)
        )
        asyncio.run(bridge.release(self.make_workspace(tmp_path)))
        (event,) = events_of_type(store, "sandbox_released")
        assert event["data"]["ok"] is True

    def test_release_never_raises_on_api_error(self, tmp_path: Path) -> None:
        store = EventStore()
        bridge = SandboxBridge(
            make_settings(tmp_path), store, transport=api_transport(delete_status=500)
        )
        asyncio.run(bridge.release(self.make_workspace(tmp_path)))  # must not raise
        (event,) = events_of_type(store, "sandbox_released")
        assert event["data"]["ok"] is False

    def test_release_connect_error_emits_ok_false(self, tmp_path: Path) -> None:
        store = EventStore()

        def failing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        bridge = SandboxBridge(
            make_settings(tmp_path),
            store,
            transport=httpx.MockTransport(failing),
        )
        asyncio.run(bridge.release(self.make_workspace(tmp_path)))
        (event,) = events_of_type(store, "sandbox_released")
        assert event["data"]["ok"] is False

    def test_release_unexpected_error_never_raises(self, tmp_path: Path) -> None:
        store = EventStore()

        def broken(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("transport exploded")

        bridge = SandboxBridge(
            make_settings(tmp_path),
            store,
            transport=httpx.MockTransport(broken),
        )
        asyncio.run(bridge.release(self.make_workspace(tmp_path)))
        (event,) = events_of_type(store, "sandbox_released")
        assert event["data"]["ok"] is False


class TestSubprocessSeams:
    """The real docker/git subprocess logic, against a fake asyncio process."""

    class FakeSubprocess:
        def __init__(self, returncode: int, stderr: bytes = b"") -> None:
            self._returncode = returncode
            self._stderr = stderr
            self.argv: tuple = ()

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", self._stderr

        @property
        def returncode(self) -> int:
            return self._returncode

    def _install(
        self,
        monkeypatch: pytest.MonkeyPatch,
        returncode: int,
        stderr: bytes = b"",
    ) -> FakeSubprocess:
        proc = self.FakeSubprocess(returncode, stderr)

        async def fake_exec(*argv: str, **kwargs: object) -> FakeSubprocess:
            proc.argv = argv
            return proc

        monkeypatch.setattr(
            bridge_module.asyncio, "create_subprocess_exec", fake_exec
        )
        return proc

    async def _call_docker_cp(self) -> None:
        await bridge_module._docker_cp("docker", "c-1", Path("/tmp/dest-x"))

    def test_docker_cp_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        proc = self._install(monkeypatch, 0)
        asyncio.run(self._call_docker_cp())
        assert proc.argv[:4] == ("docker", "cp", "c-1:/workspace/.", "/tmp/dest-x")

    def test_docker_cp_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._install(monkeypatch, 1, b"no such container")
        with pytest.raises(SandboxBridgeError, match="no such container"):
            asyncio.run(self._call_docker_cp())

    def test_remove_origin_failure_logs_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._install(monkeypatch, 1, b"fatal: no origin")
        asyncio.run(bridge_module._remove_origin(tmp_path))  # must not raise

    def test_docker_cp_creates_destination(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dest = tmp_path / "nested" / "ws"
        proc = self._install(monkeypatch, 0)
        asyncio.run(bridge_module._docker_cp("docker", "c-1", dest))
        assert dest.is_dir()
        assert proc.argv[3] == str(dest)


class TestAcpHostWiring:
    def test_disabled_uses_scratch_dir(self, tmp_path: Path) -> None:
        settings = make_settings(tmp_path, sandbox_enabled=False)
        host = AcpHost(settings, EventStore())
        info = make_envelope()
        workspace = host._prepare_workspace(info)
        assert workspace == Path(str(settings.acp_workspace_root)) / info.id
        assert workspace.is_dir()

    def _bridge_over(self, path: Path, released: list[str]) -> object:
        class FakeBridge:
            async def prepare(self, info: PromptInfo) -> SandboxWorkspace:
                return SandboxWorkspace(
                    run_id=info.id,
                    sandbox_id="sbx-9",
                    container_name="c",
                    path=path,
                )

            async def release(self, ws: SandboxWorkspace) -> None:
                released.append(ws.sandbox_id)

        return FakeBridge()

    def test_run_uses_materialized_workspace_and_releases(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        materialized = tmp_path / "materialized"
        materialized.mkdir()
        released: list[str] = []
        conn, proc = FakeConn(), FakeProc()
        install_spawn(monkeypatch, conn, proc)
        host = AcpHost(
            make_settings(tmp_path),
            EventStore(),
            bridge=self._bridge_over(materialized, released),
        )
        result = asyncio.run(host.run(make_envelope()))

        assert result.workspace == str(materialized)
        assert released == ["sbx-9"]
        # The ACP session was pointed at the materialized workspace.
        assert conn.new_session_kwargs["cwd"] == str(materialized)

    def test_bridge_failure_raises_acp_host_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailingBridge:
            async def prepare(self, info: PromptInfo) -> SandboxWorkspace:
                raise SandboxBridgeError("sandbox API unreachable")

            async def release(self, ws: SandboxWorkspace) -> None:
                raise AssertionError("release must not run when prepare failed")

        install_spawn(monkeypatch, FakeConn(), FakeProc())
        host = AcpHost(
            make_settings(tmp_path), EventStore(), bridge=FailingBridge()
        )
        with pytest.raises(AcpHostError, match="sandbox API unreachable"):
            asyncio.run(host.run(make_envelope()))

    def test_release_runs_after_session_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        materialized = tmp_path / "materialized"
        materialized.mkdir()
        released: list[str] = []
        install_spawn(monkeypatch, FakeConn(), FakeProc())
        host = AcpHost(
            # Negative prompt timeout forces the session to fail right away.
            make_settings(tmp_path, acp_prompt_timeout=-1.0),
            EventStore(),
            bridge=self._bridge_over(materialized, released),
        )
        with pytest.raises(AcpHostError):
            asyncio.run(host.run(make_envelope()))
        assert released == ["sbx-9"]

    def test_bridge_cancelled_propagates_not_acp_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class CancellingBridge:
            async def prepare(self, info: PromptInfo) -> SandboxWorkspace:
                raise asyncio.CancelledError()

            async def release(self, ws: SandboxWorkspace) -> None:
                pass

        install_spawn(monkeypatch, FakeConn(), FakeProc())
        host = AcpHost(
            make_settings(tmp_path), EventStore(), bridge=CancellingBridge()
        )
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(host.run(make_envelope()))

    def test_release_failure_after_success_logs_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        materialized = tmp_path / "materialized"
        materialized.mkdir()

        class ReleasingBridge:
            async def prepare(self, info: PromptInfo) -> SandboxWorkspace:
                return SandboxWorkspace(
                    run_id=info.id,
                    sandbox_id="sbx-9",
                    container_name="c",
                    path=materialized,
                )

            async def release(self, ws: SandboxWorkspace) -> None:
                raise RuntimeError("release exploded")

        install_spawn(monkeypatch, FakeConn(), FakeProc())
        host = AcpHost(
            make_settings(tmp_path), EventStore(), bridge=ReleasingBridge()
        )
        with caplog.at_level("WARNING"):
            result = asyncio.run(host.run(make_envelope()))
        assert result.stop_reason == "end_turn"  # the run itself still succeeds
        assert any("sandbox release failed" in r.message for r in caplog.records)

    def test_deny_config_written_into_materialized_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        materialized = tmp_path / "materialized"
        materialized.mkdir()
        released: list[str] = []
        conn, proc = FakeConn(), FakeProc()
        install_spawn(monkeypatch, conn, proc)
        host = AcpHost(
            make_settings(tmp_path, acp_denied_tools=("dangerous_tool",)),
            EventStore(),
            bridge=self._bridge_over(materialized, released),
        )
        asyncio.run(host.run(make_envelope()))
        config = json.loads(
            (materialized / "opencode.json").read_text(encoding="utf-8")
        )
        assert config["permission"] == {"dangerous_tool": "deny"}
