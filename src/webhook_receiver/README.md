# webhook_receiver — the orchestration listener and ACP host

FastAPI service (v0.2.0): accepts GitHub App webhooks, gates and dedupes
them, enqueues one typed envelope per accepted delivery, and drives one cold
`opencode` ACP session per envelope — with optional SwarmSandbox-provisioned
workspaces. All state is in-process; the design history and phase-by-phase
rationale live in
[`docs/plans/completed/orchestrator-service-simplification.md`](../../docs/plans/completed/orchestrator-service-simplification.md)
(§3 architecture, §5 decisions) and
[`docs/plans/completed/promptinfo-design.md`](../../docs/plans/completed/promptinfo-design.md).

## Request flow

```text
POST /webhooks/github
  1. size guard (413)          app.py
  2. HMAC verify (401)         github.py
  3. ping -> 200 pong          app.py
  4. JSON parse (400)          app.py
  5. transport gate -> 202 ignored   filters.py (issues.labeled, non-bot,
     |                         workflow label namespaces, fail-closed
     |                         direct-body sender allowlist)
  v
PromptInfo envelope (frozen pydantic, delivery-id dedup window 1024)
  prompt filled at enqueue by prompt_builder.py (open-ended orchestration
  direction per label class; the direct-body label runs the issue body
  verbatim)
  v
PromptQueue consumer (asyncio.Queue, FIFO)              prompt_queue.py
  no host attached (ACP_ENABLED=false) -> mark consumed
  host attached  -> AcpHost.run(info)
  v
AcpHost.run                                             acp_host.py
  workspace: SwarmSandbox materialized clone (SANDBOX_ENABLED,
  sandbox_bridge.py) or plain scratch dir
  belt-and-braces opencode.json deny-list written into the workspace
  spawn `opencode acp --cwd <workspace>`; initialize -> session/new ->
  one prompt (the envelope's own) -> collect stop reason
  session/update notifications mapped into the EventStore
  session/request_permission answered by acp_policy.py
  kill-on-exit process hygiene; sandbox released after the session
```

## Event contract

The single source of truth for event names and payload fields is the
**module docstring of [`app.py`](app.py)**; `acp_host.py` documents the
`agent_*` mapping, `prompt_queue.py` the `prompt_*` lifecycle, and
`sandbox_bridge.py` the `sandbox_*` lifecycle. Summary:

- webhook surface: `webhook_received`, `webhook_filtered`,
  `webhook_accepted`, `webhook_duplicate`
- queue lifecycle: `prompt_queued`, `prompt_consumed` (with `ok`)
- sandbox bridge: `sandbox_provisioned`, `sandbox_released`
- ACP session: `agent_session_started`, `agent_message_chunk`,
  `agent_tool_call`, `agent_usage`, `agent_permission`, `agent_finished`
  (all carry `run_id` = the envelope id)

`GET /events` streams these over SSE (`text/event-stream`): full ring-buffer
replay on subscribe, then live fan-out, `: keepalive` comments when idle
(`WEBHOOK_EVENTS_KEEPALIVE`, default 15 s). Each frame carries `id`
(monotonic store sequence), `event` (the name above), and `data` (JSON).
Consume it with any SSE client:

```sh
curl -N http://127.0.0.1:8080/events
```

The store is the dashboard concern only — the queue never reads it, and a
slow consumer merely misses events (bounded 1000-entry ring, bounded
per-subscriber queue).

## Fail-closed posture

- Signature failures, oversized bodies, and malformed JSON never reach the
  queue.
- The transport gate is the anti-loop device: bot actors and non-workflow
  labels are acknowledged but not dispatched.
- Permission requests are decided by `acp_policy.py`: deny-regex matches
  reject first, read/search/think/fetch tool kinds are allowed, everything
  else takes `ACP_DEFAULT_PERMISSION` (default `reject`), and requests with
  no matching option are cancelled. `ACP_DENIED_TOOLS` is additionally
  enforced pre-prompt by opencode itself (spike-proven stronger: the tool is
  removed before prompting).
- One cold session per envelope: a crashed or timed-out session affects
  nothing else, and the envelope surfaces as `prompt_consumed {ok: false}`.
- Durability is deliberately none (design doc §5): a lost envelope is
  recovered by GitHub redelivery.

## Modules

| Module | Responsibility |
|---|---|
| `app.py` | routes, gate wiring, `/events` SSE, stable event-name table (docstring) |
| `config.py` | every environment knob, validated at boot |
| `filters.py` | transport-level dispatch gate (+ `DIRECT_BODY_ALLOWED_SENDERS`) |
| `github.py` | HMAC `X-Hub-Signature-256` compute/verify |
| `prompt_queue.py` | frozen `PromptInfo` envelope + deduping FIFO consumer |
| `prompt_builder.py` | open-ended orchestration prompt per label class |
| `acp_host.py` | one cold opencode ACP session per envelope; event mapping |
| `acp_policy.py` | fail-closed permission decisions |
| `sandbox_bridge.py` | SwarmSandbox provisioning + docker-cp materialization |
| `event_store.py` | ring buffer + SSE subscriber fan-out |
| `acp_smoke.py` | manual real-opencode smoke (exit 0 on `end_turn`) |
| `sandbox_probe.py` | manual live bridge probe against a running API |

## Testing

```sh
.venv/bin/python -m pytest tests/ -q --cov=webhook_receiver --cov-report=term-missing
```

The suite (182 tests, > 97 percent coverage) is TestClient-based except the
`/events` tests, which bind a real uvicorn on an ephemeral port because
TestClient buffers whole responses. It must stay green in a stripped
environment (`env -i HOME=... PATH=/usr/bin:/bin PYTHONPATH=src .venv/bin/python
-m pytest tests/ -q`). The repo gate is `validation.ps1` at the repo root.

Manual smokes and CI tiering:

- tier 0 (per push/PR): `validation.ps1` — lint, scan, Pester, pytest,
  coverage gates, and `scripts/e2e-orchestration.ps1` (hermetic simulator).
- tier 1 (proposed, parked): a credential-free ACP handshake job — spawn a
  SHA-pinned opencode, `initialize`, capability negotiation, `session/new`,
  no prompt, no secrets — to catch SDK/opencode protocol drift per PR. Not
  implemented: it adds a per-PR binary download whose pinning cannot be
  verified cheaply upstream, and drift is currently caught at phase gates by
  `acp_smoke` against the pinned `agent-client-protocol==0.12.1`.
- tier 2 (not implemented): a nightly credentialed end-to-end run with a
  real repository target.
