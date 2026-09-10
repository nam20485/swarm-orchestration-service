Status: DECIDED (2026-09-10, Phase 4)
Scope: plan §7 Phase 4 — the Decision 5 swarm bridge: where the ACP-driven agent
runtime runs relative to the SwarmSandbox-provisioned environment.

## Decision — Option (iii): sandbox materializes a host workspace

SwarmSandbox stays the single provisioner of the execution environment (the
repo-at-revision clone with the swarm assets, plus the pwsh/POSIX toolchain):
the bridge asks the sandbox API to provision a container, waits for the
entrypoint clone to land in the container's `/workspace`, extracts that
known-revision clone to a host-side workspace directory (`docker cp`), and the
ACP host drives `opencode acp --cwd <host workspace>` exactly as before. The
host stays thin: it drives the client, never the swarm and never Docker
provisioning itself.

Flow per envelope (when `SANDBOX_ENABLED`):

```text
AcpHost.run(info)
  └─ SandboxBridge.prepare(info)
       ├─ POST /api/sandboxes {branch: SANDBOX_BRANCH}   → 202 {sandboxId, containerName}
       ├─ poll: docker cp <containerName>:/workspace/. <ws root>/<info.id>/
       │        ready when .git/ and .agents/skills/swarm/SKILL.md exist
       │        (proves clone success AND harness-asset presence)
       ├─ git remote remove origin   (session cannot push the harness clone cross-repo)
       └─ emit sandbox_provisioned {run_id, sandbox_id, container_name, workspace}
  └─ (one cold opencode ACP session in the materialized workspace — unchanged Phase 2 path)
  └─ SandboxBridge.release(...)  (DELETE /api/sandboxes/{id}, best-effort, shielded;
                                  reaper TTL is the crash backstop) → sandbox_released
```

When `SANDBOX_ENABLED` is unset/false the host uses the existing plain
scratch-dir behavior (Phase 2 path, untouched) — CI and dockerless local dev
stay green. When enabled but the sandbox API is unreachable or the workspace
never materializes, the bridge raises and the envelope fails closed:
`prompt_consumed {ok: false}` (no silent fallback to a scratch dir).

## Options evaluated

### (i) opencode inside the provisioned container — REJECTED

Requires opencode + node in the image (a new image layer built from this repo,
plus SwarmSandbox image-CI impact) and the model credentials living inside the
container for the whole session — widening exactly the credential surface the
existing scrub conventions minimize (today the git token exists in the
container env only for the clone and is scrubbed; the hardened container is
CapDrop-ALL, no-new-privileges, non-root). Decision 5 requires the sandbox to
provide the harness environment, not that the agent runtime be in-container.
Rejected as the largest change with the worst credential posture and no
decision requirement behind it.

### (ii) opencode host-side against the container's live /workspace — REJECTED

A bind-mounted volume needs provisioner changes and breaks the explicit
"no host binds/mounts" hardening property. `docker cp` is a snapshot, not a
live surface, so the "live workspace" framing collapses: the host would work
on a copy while the container idles — option (iii) with a vaguer ownership
story and no compensating benefit.

### (iii) opencode host-side, workspace MATERIALIZED by SwarmSandbox — CHOSEN

- Thinnest bridge: zero SwarmSandbox changes (API, provisioner, image all
  untouched); the bridge uses the existing API contract
  (`POST /api/sandboxes` → poll `GET /{id}` → `docker cp` by `containerName`
  → `DELETE /{id}`) plus the host-side docker CLI.
- Sandbox remains the single provisioner of WHAT runs (Decision 5 intent):
  repo URL, revision (branch), token scrub, and toolchain are all the
  service's existing behavior.
- Honest limits: `docker cp` is a snapshot — fine, because the session's
  publishes go through `git`/`gh` remote operations and the workspace is
  disposable per session; the bridge needs the docker CLI host-side
  (deployment requirement, documented for Phase 5 compose wiring).

## Swarm-execution boundary (asset inspection finding)

The swarm entry points are ZCode-native: `.agents/skills/swarm/SKILL.md` Start
step adopts `.zcode/agents/swarm-orchestrator.md` and the loop spawns workers
as background ZCode subagents (`run_in_background` + TaskStop/poll semantics
are ZCode tools). ZCode ships no ACP agent (plan §6 — community bridge only),
so an opencode session cannot spawn the ZCode swarm workers.

What an opencode session CAN genuinely execute from the in-repo assets today:

- the deterministic state layer — `swarm-state.ps1 init/status/...` (plain
  pwsh, no harness dependency);
- the full `gh-issue-tracking-init` skill — self-contained pwsh + `gh`
  scripts (labels, milestones, project, issues, sub-issue links);
- the swarm-plan autonomous variant → `plan_docs/application_plan.md`;
- textual adoption of the orchestrator protocol — single-agent degraded mode
  (the primary session executes rounds itself instead of spawning workers).

The multi-agent spawn loop remains harness-gated until ZCode ACP ships; the
Phase 4 demos scope themselves to the real tiers above and report the boundary
rather than simulating swarm success.

## Configuration

| Setting | Env | Default | Meaning |
|---|---|---|---|
| `sandbox_enabled` | `SANDBOX_ENABLED` | `false` | Route workspaces through the bridge |
| `sandbox_api_url` | `SANDBOX_API_URL` | `""` | SwarmSandbox API base URL (required when enabled; boot error otherwise) |
| `sandbox_branch` | `SANDBOX_BRANCH` | `development` | Branch/revision the sandbox clones into the workspace |
| `sandbox_ready_timeout` | `SANDBOX_READY_TIMEOUT` | `300` | Seconds to wait for clone materialization before failing |
| `sandbox_docker_bin` | `SANDBOX_DOCKER_BIN` | `docker` | docker CLI used for the workspace extraction |

The sandbox service itself is configured (deployment-side, unchanged) with
`SANDBOX__REPOURL` pointing at this repo (the harness clone the session runs
from) and `SANDBOX__GITTOKEN` for private clones; the bridge never sees the
token.
