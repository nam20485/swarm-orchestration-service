# swarm-orchestration-service

The orchestration listener and ACP host for the swarm pipeline (v0.2.0): a
GitHub webhook listener that turns label events into typed `PromptInfo`
envelopes and drives an agent CLI (opencode first) over the Agent Client
Protocol. No always-on agent server, no prompt-encoded state machine — the
agent decides workflow progression from live tracking state.

> Template lineage: this repository is a fork-style clone of the
> `intel-agency/agent-context` template (Decision 8 in
> [`docs/plans/completed/orchestrator-service-simplification.md`](docs/plans/completed/orchestrator-service-simplification.md)).
> The template stays the substrate from which new downstream instances are
> cloned; shared harness assets flow into this repo through the `upstream`
> remote, one reviewed merge per sync.

Guides: [architecture](docs/architecture.md) — what the service is, its
components, and how a delivery flows; [usage](docs/usage.md) — deploy,
expose via Tailscale Funnel, wire the GitHub App, trigger and observe runs.

## How it works

```text
GitHub App webhook
  | HMAC verify (X-Hub-Signature-256)
  v
POST /webhooks/github ---- transport gate: only issues.labeled by a
  |                        non-bot sender with a workflow label dispatches
  v
PromptInfo queue ---------- typed asyncio.Queue envelope, delivery-id dedup,
  |                        one FIFO consumer
  v
ACP host ------------------ one cold `opencode acp --cwd <workspace>` session
  |                        per envelope; fail-closed permission policy;
  |                        zero host-side model pins
  v
SwarmSandbox bridge ------- optional (SANDBOX_ENABLED): the sandbox provisions
                           the harness clone that becomes the session cwd
```

Every step emits events to the in-process EventStore, and `GET /events`
streams them to a dashboard over SSE. The service-level details — endpoints,
event contract, queue semantics, permission policy — live in
[`src/webhook_receiver/README.md`](src/webhook_receiver/README.md).

## Endpoints

| Path | Method | Purpose |
|---|---|---|
| `/webhooks/github` | POST | GitHub App deliveries (HMAC-verified, gated, deduped) |
| `/health` | GET | liveness probe |
| `/events` | GET | SSE stream of the event store (dashboard concern) |

In the compose deployment Caddy exposes only `/webhooks/github` and `/health`
publicly; `/events` stays listener-local (internal network or tunnel).

## Prerequisites

- **Python 3.12+** — the service and its test suite.
- **PowerShell 7+** (`pwsh`) — repo scripts and the validation gate.
- **opencode** — required only for live dispatch: the ACP host drives
  `opencode acp` (floor 0.15.10; verified against 1.18.30). The simulator,
  the test suite, and `ACP_ENABLED=false` runs never invoke it.
- **Docker** (optional) — the SwarmSandbox bridge (`SANDBOX_ENABLED=true`)
  and the compose deployment.

## Configuration

Every knob is an environment variable parsed in
[`src/webhook_receiver/config.py`](src/webhook_receiver/config.py)
(`DIRECT_BODY_ALLOWED_SENDERS` is read live in
[`src/webhook_receiver/filters.py`](src/webhook_receiver/filters.py)):

| Variable | Default | Purpose |
|---|---|---|
| `OS_WEBHOOK_SECRET` | *(required)* | GitHub App webhook secret for HMAC verification; missing refuses to boot |
| `WEBHOOK_HOST` | `0.0.0.0` | listener bind address |
| `WEBHOOK_PORT` | `8080` | listener port |
| `WEBHOOK_MAX_BODY_BYTES` | `26214400` | larger webhook bodies are rejected with 413 |
| `WEBHOOK_LOG_LEVEL` | `info` | uvicorn and logging level |
| `WEBHOOK_EVENTS_KEEPALIVE` | `15` | idle seconds before the SSE stream emits a keepalive comment (must be positive) |
| `ACP_ENABLED` | `true` | drive opencode over ACP per envelope; `false` keeps the queue-consumer placeholder (no agent sessions) |
| `ACP_OPENCODE_BIN` | PATH, then `~/.opencode/bin/opencode` | opencode binary location |
| `ACP_WORKSPACE_ROOT` | `/tmp/swarm-acp-workspaces` | root for per-run session workspaces (the repo itself is never used) |
| `ACP_STEP_TIMEOUT` | `30` | seconds per protocol step (initialize, session open) |
| `ACP_PROMPT_TIMEOUT` | `600` | seconds per prompt (one cold session per envelope) |
| `ACP_DEFAULT_PERMISSION` | `reject` | action for unclassified permission requests: `reject` (headless-safe) or `allow_once` |
| `ACP_DENY_PATTERNS` | *(empty)* | comma-separated regexes (case-insensitive) that always reject a permission request; validated at boot |
| `ACP_DENIED_TOOLS` | *(empty)* | tools denied pre-prompt via the workspace `opencode.json` permission config |
| `SANDBOX_ENABLED` | `false` | provision session workspaces through the SwarmSandbox API |
| `SANDBOX_API_URL` | *(required when enabled)* | SwarmSandbox API base URL; validated at boot |
| `SANDBOX_BRANCH` | `development` | branch the sandbox clones into the workspace |
| `SANDBOX_READY_TIMEOUT` | `300` | seconds to wait for the workspace to materialize host-side |
| `SANDBOX_DOCKER_BIN` | `docker` | docker CLI used for the workspace extraction |
| `DIRECT_BODY_ALLOWED_SENDERS` | *(empty, fail-closed)* | comma-separated senders allowed to dispatch the `gh-issue-tracking:direct-body` verbatim-prompt path |

Failure posture: an enabled-but-broken sandbox fails the envelope (no silent
scratch-dir fallback), and permission requests that match no configured
option are cancelled — the listener never hangs on an agent ask.

## Running locally

Create the venv (or let `validation.ps1 -Step python` /
`scripts/e2e-orchestration.ps1` bootstrap it):

```sh
python3 -m venv .venv
.venv/bin/pip install -r src/webhook_receiver/requirements-dev.txt
```

Export the required `OS_WEBHOOK_SECRET` (the GitHub App webhook secret — the
listener refuses to boot without it), then:

```sh
.venv/bin/python -m webhook_receiver                 # bare listener
```

With Docker, compose brings the listener plus a locked-down Caddy proxy
(Caddyfile allows only the webhook path and health probe; Caddy terminates on
`:80` or automatic HTTPS via `WEBHOOK_SITE_ADDRESS`):

```sh
cp .env.example .env                 # then fill in OS_WEBHOOK_SECRET
docker compose up --build --detach   # reads compose.yaml; secrets come from the gitignored .env
```

## Testing

```sh
pwsh -NoProfile -File ./validation.ps1                # full gate: what CI runs
pwsh -NoProfile -File ./validation.ps1 -Step python   # service suite only
.venv/bin/python -m pytest src/webhook_receiver/tests/ -q
```

The gate runs markdownlint plus a relative-link check, PSScriptAnalyzer and
gitleaks, the Pester suite over the PowerShell assets, the pytest suite for
this service (coverage >= 85 percent enforced), and the e2e orchestration
smoke below. The suite must also stay green in a stripped environment
(`env -i HOME=... PATH=/usr/bin:/bin PYTHONPATH=src .venv/bin/python -m pytest
src/webhook_receiver/tests/ -q`), which is how the CI-sim is verified.

Manual smokes (never run by validation or CI):

- `pwsh scripts/e2e-orchestration.ps1` — hermetic simulator: boots the real
  listener on loopback, drives five signed webhook scenarios, asserts the
  EventStore outcomes. Exit 0 pass, 1 fail; CI-safe, ~3 seconds.
- `PYTHONPATH=src .venv/bin/python -m webhook_receiver.acp_smoke` — one real
  opencode ACP session end-to-end (needs opencode; exit 0 on `end_turn`).
- `PYTHONPATH=src .venv/bin/python -m webhook_receiver.sandbox_probe` — live
  SwarmSandbox bridge probe (needs a running sandbox API and docker).
- `pwsh src/SwarmSandbox/scripts/e2e-sandbox.ps1` — sandbox provisioner proof
  (needs the sandbox image and docker).

CI tiering: the per-push/per-PR gate is `validation.ps1` (tier 0). A tier-1
credential-free ACP handshake against a pinned opencode binary and a tier-2
nightly credentialed end-to-end run are documented in
[`src/webhook_receiver/README.md`](src/webhook_receiver/README.md) but not
implemented.

## Repository layout

| Path | Description |
|---|---|
| [`AGENTS.md`](AGENTS.md) | operating manual for AI agents working in this repo |
| `.agents/` | durable memory, rules, and skills (inherited from the template) |
| `docs/architecture.md`, `docs/usage.md` | service guides: components and delivery flow; deploy, trigger, observe |
| `docs/plans/` | plans of record — open/parked at the top level, landed plans archived in `completed/` (incl. the simplification plan that built this service) |
| `scripts/` | repo helper scripts, incl. the e2e orchestration smoke |
| `src/webhook_receiver/` | the service: listener, queue, ACP host, sandbox bridge (see its README) |
| `src/SwarmSandbox/` | Aspire + Docker sandbox-provisioning service (see [`src/SwarmSandbox/ARCHITECTURE.md`](src/SwarmSandbox/ARCHITECTURE.md)) |
| `compose.yaml`, `Caddyfile`, `Dockerfile.webhook` | listener + digest-pinned Caddy proxy deployment |
| `spikes/acp/` | phase-0 ACP spike evidence and re-run steps |
| `validation.ps1` | build/scan/test gate mirroring CI |

## Contributing

Read [`AGENTS.md`](AGENTS.md) first: branches follow `dev/<name>`, every
change passes `validation.ps1`, and `/safe-commit` runs before committing.
Plan documents of record live under `docs/plans/` — landed plans are
archived in `docs/plans/completed/`; open or parked ones sit at the top
level (see [`docs/plans/README.md`](docs/plans/README.md)).
