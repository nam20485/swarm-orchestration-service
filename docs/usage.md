# Usage Guide

How to deploy the service, expose it to GitHub, trigger runs, and observe
them. What the components are and why they are shaped this way lives in
[architecture.md](architecture.md); the complete environment-variable table
lives in the [root README](../README.md#configuration).

## 1. Pick a run mode

| Mode | Command | Dispatches agents? | Needs |
|---|---|---|---|
| Simulator / CI | `pwsh scripts/e2e-orchestration.ps1` | no (ACP_ENABLED=false) | nothing beyond the repo |
| Host-run live dispatch | `.venv/bin/python -m webhook_receiver` | **yes** | opencode + `gh` on the host |
| Compose deployment | `docker compose up --build --detach` | no — image has no opencode (listener-only) | Docker |
| Sandbox workspaces | host-run + `SANDBOX_ENABLED=true` | yes | SwarmSandbox API + docker |

Host-run live dispatch is the validated mode: every accepted envelope spawns
one cold `opencode acp` session that inherits the host environment, so
opencode must be authenticated to a model provider and `gh` to GitHub before
a real run. The compose image is a slim Python listener — it verifies, gates,
dedupes, and acknowledges deliveries, but a session attempted inside it fails
(the envelope surfaces as `prompt_consumed {ok: false}`).

## 2. Configure

Create a `.env` next to `compose.yaml` (gitignored; seed it from
[`.env.example`](../.env.example) — every variable, grouped required vs
optional) or export variables for a host run. The essentials:

| Variable | Required | Purpose |
|---|---|---|
| `OS_WEBHOOK_SECRET` | always | GitHub App webhook secret; the listener refuses to boot without it |
| `ACP_ENABLED` | dispatch | `false` keeps the no-op consumer (tests, listener-only) |
| `ACP_PROMPT_TIMEOUT` | long tasks | seconds per prompt (default 600); raise for long agent sessions |
| `ACP_DENY_PATTERNS` / `ACP_DENIED_TOOLS` | hardening | regex deny-list for permission asks / tools denied pre-prompt |
| `SANDBOX_ENABLED` / `SANDBOX_API_URL` | sandbox mode | route workspaces through SwarmSandbox provisioning |
| `DIRECT_BODY_ALLOWED_SENDERS` | direct-body | trusted senders for the verbatim-prompt label; empty = the label never dispatches (fail-closed) |

Full table with defaults: [README § Configuration](../README.md#configuration).

## 3. Expose it to the internet

GitHub must reach the webhook over public HTTPS. The established pattern:

```sh
tailscale funnel 80    # publishes a stable https://<host>.ts.net URL onto host :80
```

Funnel terminates TLS upstream; Caddy serves plain HTTP on `:80` and is the
entire public surface (`/webhooks/github` + `/health` only, 404 for
everything else). Alternative: set `WEBHOOK_SITE_ADDRESS=<hostname>` and let
Caddy do automatic HTTPS on `:443` — but never combine that with the funnel
(both bind `:443`).

Verify before wiring GitHub: `curl https://<host>.ts.net/health` returns
`200`.

## 4. Wire the GitHub App

In the GitHub App settings (or repository webhook settings):

1. **Webhook URL**: `https://<host>.ts.net/webhooks/github`
2. **Content type**: `application/json`
3. **Secret**: the same value as `OS_WEBHOOK_SECRET`
4. **Events**: subscribe to **Issues** — the gate dispatches only on
   `issues.labeled`

Install the App on the repositories you want tracked, then deliver a ping
from the App's recent-deliveries view: expect HTTP 200 and no events on
`/events` (pings emit nothing).

## 5. Trigger a run

Label an issue as a human (bot actors are ignored) with a workflow label:

| Label | Dispatch behavior |
|---|---|
| `orchestration:*` | lifecycle workflows (e.g. `orchestration:plan-approved`); body-named dynamic dispatch within the namespace |
| `gh-issue-tracking:*` | hierarchy workflows (init, plan/epic/story lifecycle) |
| `implementation:ready`, `implementation:complete` | implementation path on an already-tracked app |
| `gh-issue-tracking:direct-body` | the **issue body verbatim** as the agent prompt — only from senders in `DIRECT_BODY_ALLOWED_SENDERS` |

The webhook returns `202` immediately; work happens in the background. The
agent reads live tracking state (`gh issue list`, `gh pr list`, …), does the
work on a non-default branch, opens PRs/labels, and finishes. Any other label
or event type is acknowledged (`202`) and ignored — it never dispatches.

## 6. Observe

```sh
curl -N http://127.0.0.1:8080/events   # SSE: replay, then live; keepalive every 15 s
```

A healthy dispatch produces this sequence (frames carry monotonic `id`, event
name, JSON `data`; `run_id` ties the agent events to the envelope):

```text
webhook_received -> webhook_accepted -> prompt_queued
  -> [sandbox_provisioned]            # SANDBOX_ENABLED only
  -> agent_session_started -> agent_tool_call / agent_message_chunk /
     agent_permission / agent_usage   -> agent_finished
  -> [sandbox_released] -> prompt_consumed {ok: true}
```

`/events` is listener-local by design — it is not routed through the public
Caddy surface. Reach it on the listener port directly (host run), or via an
SSH tunnel / tailnet serve.

## 7. Troubleshoot

| Symptom | Meaning / fix |
|---|---|
| delivery answered `401` | signature mismatch — webhook secret differs from `OS_WEBHOOK_SECRET` |
| `413` / `400` | body over `WEBHOOK_MAX_BODY_BYTES` / malformed JSON (never dispatched) |
| `202` but only `webhook_filtered` | gate said no: bot sender, non-workflow label, or `direct-body` from a non-allowlisted sender (`reason` field says which) |
| `webhook_duplicate` | GitHub redelivery inside the dedup window (1024 deliveries) — already processed; nothing to do |
| `prompt_consumed {ok: false}` | the agent session failed: opencode missing/unauthenticated, prompt timeout (raise `ACP_PROMPT_TIMEOUT`), or a permission policy cancellation — `error` field carries the cause |
| sandbox mode: envelope fails fast | fail-closed by design when the sandbox API is unreachable — check `SANDBOX_API_URL` and docker; no silent scratch fallback |
| nothing at all in `/events` | you hit a different instance than the one GitHub delivers to, or the funnel is down (`/health` through the public URL proves the path) |

## 8. Operational notes

- **Durability is none, on purpose.** Restarting the listener drops in-flight
  envelopes; recovery is GitHub's webhook redelivery (App settings → recent
  deliveries → Redeliver). Dedup state is also in-process, so a redelivery
  after a restart re-runs.
- **One cold session per envelope** — a crashed or timed-out session affects
  nothing else; the queue is FIFO, so long sessions delay later ones (raise
  `ACP_PROMPT_TIMEOUT` for long tasks rather than letting them die).
- **Workspaces** live under `ACP_WORKSPACE_ROOT` (default
  `/tmp/swarm-acp-workspaces/<envelope id>`) unless the sandbox provisions
  them; the repo the listener runs in is never used as a workspace.
- **Cutover from the old stack** (funnel already fronts `:80`) follows the
  owner-gated checklist in
  [`old-stack-decommission.md`](old-stack-decommission.md).

## 9. Verify changes before deploying

```sh
pwsh -NoProfile -File ./validation.ps1          # the CI gate: lint, scan, tests, e2e simulator
PYTHONPATH=src .venv/bin/python -m webhook_receiver.acp_smoke   # one real opencode session
PYTHONPATH=src .venv/bin/python -m webhook_receiver.sandbox_probe  # live sandbox bridge
```
