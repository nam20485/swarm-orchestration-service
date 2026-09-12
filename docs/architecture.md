# Architecture

What this service is, the components it is built from, and how one webhook
delivery flows through them. Operational steps (deploy, expose, trigger,
observe) live in the [usage guide](usage.md); the design history and the
rationale for every decision live in
[`docs/plans/completed/orchestrator-service-simplification.md`](plans/completed/orchestrator-service-simplification.md).

## Description

`swarm-orchestration-service` is the pipeline's orchestration listener: a
GitHub webhook receiver that turns label events into typed work items and an
ACP host that drives an agent CLI (opencode first) to execute them. It
replaces the old `orchestrator-service` dispatch. Two properties define it:

- **No always-on agent server.** The old stack ran `opencode serve` in a
  container and attached one-shot clients to it. Here every accepted delivery
  spawns one cold `opencode acp` session that lives exactly as long as the
  work item and is killed afterward.
- **No prompt-encoded state machine.** The old stack chained workflow steps
  by applying the *next label* from a 431-line match table. Here the prompt
  is an open-ended direction: the agent reads live tracking state over `gh`
  and decides the next step itself.

State is deliberately in-process and non-durable — a lost envelope is
recovered by GitHub's webhook redelivery, not by a local store.

## Components

| Component | What it is | Runs where |
|---|---|---|
| `webhook-receiver` | the service: FastAPI listener + PromptInfo queue + ACP host (modules below) | container (listener) or host venv (listener + live dispatch) |
| `webhook-proxy` | digest-pinned Caddy; the public surface — only `/webhooks/github` and `/health`, everything else 404 | container, host port `:80` |
| `opencode` | external binary the ACP host spawns per envelope; **never a container here** | host (or wherever the listener runs) |
| SwarmSandbox | optional external provisioner (Aspire + Docker) that materializes session workspaces | separate deployment; see [`src/SwarmSandbox/ARCHITECTURE.md`](../src/SwarmSandbox/ARCHITECTURE.md) |

### Listener modules ([`src/webhook_receiver/`](../src/webhook_receiver/))

| Module | Responsibility |
|---|---|
| `app.py` | routes, gate wiring, `/events` SSE, the stable event-name table (module docstring is its single source of truth) |
| `config.py` | every environment knob, validated at boot |
| `filters.py` | transport-level dispatch gate (label namespaces, non-bot sender, fail-closed `direct-body` sender allowlist) |
| `github.py` | HMAC `X-Hub-Signature-256` compute/verify |
| `prompt_queue.py` | frozen pydantic `PromptInfo` envelope + deduping FIFO consumer |
| `prompt_builder.py` | open-ended orchestration prompt composed per label class |
| `acp_host.py` | one cold `opencode acp` session per envelope; maps protocol traffic to events |
| `acp_policy.py` | fail-closed permission decisions for the session |
| `sandbox_bridge.py` | SwarmSandbox provisioning + `docker cp` workspace materialization |
| `event_store.py` | ring buffer + SSE subscriber fan-out |

## How a delivery flows

```text
GitHub App webhook (issues.labeled)
  |  HMAC verify (401 on bad signature)                    github.py
  v
transport gate -> 202 ignored                              filters.py
  |  only: non-bot sender + workflow label
  |  (orchestration:* | gh-issue-tracking:* |
  |   implementation:ready|complete | direct-body*)
  v
PromptInfo envelope, frozen; prompt built at enqueue;      prompt_builder.py
  |  delivery-id dedup (window 1024; redelivery -> 202 duplicate)
  v
PromptQueue FIFO consumer                                  prompt_queue.py
  |  ACP_ENABLED=false -> mark consumed, no session
  v
AcpHost.run                                                acp_host.py
  |  workspace: SwarmSandbox clone (SANDBOX_ENABLED=true)
  |  or plain scratch dir (/tmp/swarm-acp-workspaces)
  |  belt-and-braces opencode.json deny-list in the workspace
  |  spawn `opencode acp --cwd <workspace>`: initialize ->
  |  session/new -> one prompt -> collect stop reason -> kill
  v
events for every step                                      event_store.py
  -> GET /events SSE (listener-local; dashboard concern)
```

The agent session itself works against GitHub through the `gh` CLI in its
inherited environment — query tracking state, branch, open PRs, apply labels.
The listener never pins a model and never acts on GitHub itself.

## Deployment topology

```text
public internet (GitHub)
  |
  |  HTTPS terminated by the funnel/proxy layer
  v
tailscale funnel (or any TLS ingress) -> host :80
  |
  v
Caddy (webhook-proxy) -- /webhooks/github, /health ONLY
  |
  v
webhook-receiver :8080  ---- GET /events SSE (listener-local only)
  |
  +--[dispatch]--> opencode acp (host binary) --> gh CLI --> GitHub
  |
  +--[optional]--> SwarmSandbox API --> docker container workspace
```

Two run modes matter operationally:

- **Compose deployment** — listener + Caddy only. The image is a slim
  Python image with **no opencode inside**, so this mode receives, verifies,
  and acknowledges deliveries but cannot execute live agent sessions without
  further image/env work.
- **Host-run listener** — the validated live-dispatch mode: the listener
  runs in a venv on the host, where `opencode` (authenticated to a model
  provider) and `gh` (authenticated to GitHub) are available to each session.

## Eventing

Every step emits a named event into an in-process ring buffer (bounded 1000
entries); `GET /events` streams the buffer over SSE with full replay on
subscribe, live fan-out, and idle keepalives. The 15-event contract —
`webhook_*`, `prompt_*`, `sandbox_*`, `agent_*` — is documented in the
`app.py` module docstring and summarized in
[`src/webhook_receiver/README.md`](../src/webhook_receiver/README.md). This
is the surface a dashboard consumes; none is built yet (the old stack's
dashboard was not ported).

## Design records

- Plan of record (phases, decisions, rejected options):
  [`plans/completed/orchestrator-service-simplification.md`](plans/completed/orchestrator-service-simplification.md)
- PromptInfo envelope and queue semantics:
  [`plans/completed/promptinfo-design.md`](plans/completed/promptinfo-design.md)
- Sandbox bridge decision (option iii) :
  [`plans/completed/phase4-bridge-design.md`](plans/completed/phase4-bridge-design.md)
- Old-stack cutover/rollback (owner-gated):
  [`old-stack-decommission.md`](old-stack-decommission.md)
