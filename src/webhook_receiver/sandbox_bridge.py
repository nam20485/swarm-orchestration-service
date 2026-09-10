"""SwarmSandbox bridge (Phase 4, plan §5 Decision 5 / §7 Phase 4).

Replaces the Phase 2 plain scratch workspace with a sandbox-provisioned one
when ``SANDBOX_ENABLED`` is set: the bridge asks the SwarmSandbox API to
provision a container (its entrypoint clones the configured harness repo at
``SANDBOX_BRANCH`` into ``/workspace``, scrubbing the git token), waits for
the clone to land, extracts the known-revision clone to a host workspace via
``docker cp``, and hands that directory to the ACP host as the session cwd.
The sandbox stays the single provisioner of WHAT runs (repo-at-revision +
toolchain); the host drives the client — see
docs/plans/phase4-bridge-design.md for the decision and rejected options.

Lifecycle per envelope: ``prepare`` (POST /api/sandboxes → poll-materialize →
``sandbox_provisioned`` event), the ACP session runs, then ``release``
(DELETE /api/sandboxes/{id} → ``sandbox_released``); the service's reaper TTL
is the crash backstop. Failure is fail-closed: an unreachable API or a
workspace that never materializes raises :class:`SandboxBridgeError`, which
surfaces as ``prompt_consumed {ok: false}`` — never a silent scratch-dir
fallback. The extracted workspace's ``origin`` remote is removed so the
session cannot push the harness clone to the wrong repository.

The SwarmSandbox API is unauthenticated by design (ARCHITECTURE.md §M3); the
bridge adds no credentials and never sees the clone token (it lives only in
the sandbox service's own configuration).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from webhook_receiver.config import Settings
    from webhook_receiver.event_store import EventStore
    from webhook_receiver.prompt_queue import PromptInfo

logger = logging.getLogger(__name__)

# The entrypoint clone runs after the container reports Running, so the first
# extraction usually copies an empty/partial workspace; poll until the clone
# markers appear.
_POLL_INTERVAL_SECONDS = 2.0
_HTTP_TIMEOUT_SECONDS = 15.0
# Proves both clone success and harness-asset presence in the extracted tree.
_READY_MARKERS = (".git", Path(".agents") / "skills" / "swarm" / "SKILL.md")


class SandboxBridgeError(RuntimeError):
    """The sandbox could not be provisioned or the workspace never materialized."""


@dataclass(frozen=True)
class SandboxWorkspace:
    """A materialized workspace plus the sandbox that backed it."""

    run_id: str
    sandbox_id: str
    container_name: str
    path: Path


async def _docker_cp(docker_bin: str, container: str, dest: Path) -> None:
    """Extract the container's /workspace contents into *dest* (snapshot)."""
    dest.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        docker_bin,
        "cp",
        f"{container}:/workspace/.",
        str(dest),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise SandboxBridgeError(
            f"docker cp {container}:/workspace/. failed: "
            f"{stderr.decode(errors='replace').strip()}"
        )


async def _remove_origin(workspace: Path) -> None:
    """Best-effort: drop the clone's origin so a session cannot push the
    harness repo cross-repo; publishes go through ``gh`` against the target."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "remote",
        "remove",
        "origin",
        cwd=workspace,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            "git remote remove origin failed in %s: %s",
            workspace,
            stderr.decode(errors="replace").strip(),
        )


class SandboxBridge:
    """Provisions sandbox-backed workspaces for one ACP host."""

    def __init__(
        self,
        settings: Settings,
        store: EventStore,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._settings.sandbox_api_url.rstrip("/"),
            timeout=_HTTP_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    async def prepare(self, info: PromptInfo) -> SandboxWorkspace:
        """Provision a sandbox and materialize its clone as the run workspace."""
        async with self._client() as client:
            sandbox_id, container_name = await self._create_sandbox(client)
            workspace = self._workspace_dir(info.id)
            try:
                await self._materialize(container_name, workspace)
            except Exception:
                # Do not leak a container whose workspace never materialized;
                # the reaper TTL remains the backstop if this cleanup fails.
                await self._delete_sandbox(client, sandbox_id)
                raise
        await _remove_origin(workspace)
        self._store.emit(
            "sandbox_provisioned",
            run_id=info.id,
            sandbox_id=sandbox_id,
            container_name=container_name,
            workspace=str(workspace),
        )
        return SandboxWorkspace(
            run_id=info.id,
            sandbox_id=sandbox_id,
            container_name=container_name,
            path=workspace,
        )

    async def release(self, workspace: SandboxWorkspace) -> None:
        """Delete the backing sandbox (best-effort; never raises)."""
        try:
            async with self._client() as client:
                ok = await self._delete_sandbox(client, workspace.sandbox_id)
        except Exception as exc:
            logger.warning(
                "sandbox release failed sandbox_id=%s: %s",
                workspace.sandbox_id,
                exc,
            )
            ok = False
        self._store.emit(
            "sandbox_released",
            run_id=workspace.run_id,
            sandbox_id=workspace.sandbox_id,
            ok=ok,
        )

    def _workspace_dir(self, envelope_id: str) -> Path:
        root = (
            Path(self._settings.acp_workspace_root)
            if self._settings.acp_workspace_root
            else Path("/tmp") / "swarm-acp-workspaces"
        )
        return root / envelope_id

    async def _create_sandbox(self, client: httpx.AsyncClient) -> tuple[str, str]:
        try:
            response = await client.post(
                "/api/sandboxes", json={"branch": self._settings.sandbox_branch}
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise SandboxBridgeError(
                f"sandbox API {self._settings.sandbox_api_url!r} unreachable or "
                f"unhealthy: {exc}"
            ) from exc
        sandbox_id = body.get("sandboxId")
        container_name = body.get("containerName")
        if not sandbox_id or not container_name:
            raise SandboxBridgeError(
                f"sandbox API create response missing sandboxId/containerName: {body!r}"
            )
        return str(sandbox_id), str(container_name)

    async def _materialize(self, container_name: str, workspace: Path) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.sandbox_ready_timeout
        docker_bin = self._settings.sandbox_docker_bin
        while True:
            await _docker_cp(docker_bin, container_name, workspace)
            if all((workspace / marker).exists() for marker in _READY_MARKERS):
                return
            if loop.time() >= deadline:
                raise SandboxBridgeError(
                    f"sandbox workspace did not materialize within "
                    f"{self._settings.sandbox_ready_timeout:.0f}s (in-container "
                    f"clone may have failed; check the sandbox container logs)"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _delete_sandbox(
        self, client: httpx.AsyncClient, sandbox_id: str
    ) -> bool:
        try:
            response = await client.delete(f"/api/sandboxes/{sandbox_id}")
        except httpx.HTTPError as exc:
            logger.warning("sandbox DELETE %s failed: %s", sandbox_id, exc)
            return False
        # 404 = already gone: release is idempotent, so that is success.
        return response.status_code in (200, 202, 204, 404)
