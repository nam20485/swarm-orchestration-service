# Plan: Service Web UI (Orchestration Observability)

Status: IN PROGRESS — owner decisions folded 2026-10-15 (see Decisions);
W0 LANDED (PR #35, `549382b`); W1 implemented (branch `dev/webui-w1`,
PR pending); W2 (the UI) is next
Date: 2026-10-14 (decisions folded 2026-10-15; W0+W1 landed 2026-10-15)

## Goal

A browser UI over this service's event surface: live observability of the
webhook → queue → sandbox → ACP-agent pipeline, with a per-run trace view that
shows **ALL protocol traces — the complete `session/update` stream — not a
curated subset of "important" events** (owner direction, 2026-10-14, lifting
the 2026-09-23 park).

## Investigation findings

### The "ALL traces" decision already exists — it is plan-of-record Decision 7

The owner's recollection is correct and maps to
[`docs/plans/completed/orchestrator-service-simplification.md`](completed/orchestrator-service-simplification.md)
§5 Decision 7: *"Dashboard/progress: ACP protocol events only (`session/update`
→ the SSE `EventStore` as new event types); the opencode-stderr glyph parser is
deleted."* The old stack's trace feed was the opencode client's stderr, decoded
by a glyph parser (`run_stream.py`) whose `filters.py` `_DEFAULT_BLACKLIST`
discarded ~73% of run-log lines as repetition (bus `message.part` churn,
permission-echo, loop counters, config probes, blank lines…). Decision 7
replaced that entire path: the ACP protocol stream **is** the trace feed. No
blacklist was to be reintroduced.

### But the current implementation does NOT forward all traces

`acp_host.py` maps only **4 of the 13** `session_update` kinds in the pinned
`agent-client-protocol` SDK into events:

| Mapped today → event | Dropped today (logged, not emitted) |
|---|---|
| `agent_message_chunk` → `agent_message_chunk` | `user_message_chunk` (the prompt echo) |
| `tool_call`, `tool_call_update` → `agent_tool_call` | `agent_thought_chunk` |
| `usage_update` → `agent_usage` | `plan` (full snapshot), `plan_update`, `plan_removed` |
| | `available_commands_update`, `current_mode_update`, `session_info_update`, `config_option_update` |

The `acp_host.py` module docstring says so explicitly: plan deltas, mode
changes, thought chunks, available commands are "consumed and ignored — extend
the mapping here if the dashboard needs them". **The web UI is the thing that
needs them.** Unknown future kinds are also silently dropped. Making "ALL
traces" literal is therefore a backend change (Phase W0 below), not just a UI.

### What the web UI itself has (and doesn't have)

- **No prior design.** Project memory recorded the UI as "NEVER DESIGNED,
  parked (owner, 2026-09-23)" over the complexity threshold; no design doc
  existed anywhere in the chain. The park is lifted by the owner's direction
  to plan it now.
- **The backend surface exists**: `GET /events` SSE (full ring-buffer replay on
  subscribe, live fan-out, keepalive) + the **stable 15-event contract**
  (`app.py` module docstring, mirrored in `src/webhook_receiver/README.md`,
  additive changes only). `skill-plan.md`'s "No dashboard" non-goal was about
  that skill, not this work.
- **Per-run persistence landed since** (PR #32, `harness-trace-parity`):
  `webhook_receiver.trace_log` writes a restart-surviving per-run record
  under `ACP_TRACE_ROOT` (default `logs/runs/<run_id>/`: `harness.log` =
  every harness stderr line, flushed, redacted, noise-unfiltered;
  `manifest.json` = identity + outcome; retention `ACP_TRACE_KEEP_RUNS`,
  default 50, pruned oldest-first). That is the harness **stderr**, not the
  protocol event stream — the ring buffer remains the only *event*
  persistence — but W1 builds on these directory/knob conventions rather
  than inventing parallel ones.
- **Constraints to design around**:
  - `EventStore` is an in-memory ring (`maxlen=1000`, not config-wired; only
    `WEBHOOK_EVENTS_KEEPALIVE` is a knob) — a restart wipes everything, and a
    busy run's thought/message chunks can churn the ring quickly.
  - Caddy exposes only `/webhooks/github` + `/health`; `/events` is
    listener-local (internal network / SSH tunnel) by design, with no auth.
  - Compose mode is listener-only (no opencode in the image) — `agent_*`
    events only flow in host-run mode.

### Reference: the old stack's dashboard (frozen `nam20485/orchestrator-service`)

`dashboard.py` (948 lines) served: `/overview`, `/active`, `/events/stream`
(SSE), `/runs` + `/runs/{stem}/logs` + `/runs/{stem}/narrative` (disk scan of
per-run logs, capped at 100), `/webhooks` + `/webhooks/{id}`, plus
old-stack-specific beads surfaces (`/beads`, `/graph`, `/pages/*`) and seven
static HTML pages, behind a dashboard-token cookie. Much of it (beads, bvr
pages, the stderr narrative) dies with the stderr parser per Decision 7 and is
**not** portable. What IS worth porting as pattern: token auth, disk-backed run
history, the static-HTML-no-build-step approach.

The only in-tree web UI is `src/SwarmSandbox/SwarmSandbox.Web` (Blazor WASM,
sandbox lifecycle — a different concern, .NET backend).

## Proposed shape

**Relationship to `harness-trace-parity` S4** (same function, two plans):
S4's event half ("recover the agent's voice" — thought chunks + plan deltas
into the event stream) is subsumed by W0, which maps **all 13** kinds. When
executing both plans, W0 is the superset implementation of the widening: land
W0 first (or as the same branch), take S4's unique remainder — rendering
thought/plan into `harness.log` in the golden style (`[acp] Thinking: …`) —
as the S4 remnant, and reconcile the event names once in W0's favor
(protocol-faithful `agent_thought_chunk`, not S4's sketched `agent_thought`;
S6's docs sweep reflects the final names). Note S6 already owns correcting
the "15-event contract" count (14 names are actually emitted today).

Backend-first, three small phases, each its own PR:

1. **W0 — ALL-traces contract widening** (no UI): `acp_host.session_update`
   forwards **every** kind. Known kinds get typed events (`agent_thought_chunk`,
   `agent_plan`/`agent_plan_update`/`agent_plan_removed` for the three plan
   kinds, `agent_commands_update`,
   `agent_mode_update`, `agent_session_info`, `agent_config_update`,
   `user_message_chunk`); anything unrecognized emits a generic `agent_update`
   passthrough (`kind` + full JSON-safe payload) so unknown kinds are never
   dropped again. All carry `run_id`. No server-side filtering anywhere — the
   stream carries everything; **filtering is a UI concern only**. Ring size
   becomes a knob (`WEBHOOK_EVENTS_MAXLEN`). Contract table updated in all
   three mirrors (`app.py` docstring, `src/webhook_receiver/README.md`,
   `docs/usage.md`).
2. **W1 — Run history persistence**: append every event to
   `ACP_TRACE_ROOT/<run_id>/events.jsonl` — a sibling of `trace_log`'s
   `harness.log`/`manifest.json` — reusing `ACP_TRACE_KEEP_RUNS` retention
   (same directory, same lifecycle) and the best-effort
   never-fails-a-dispatch posture. Gated by **its own flag** (owner,
   2026-10-15): `WEBHOOK_EVENTS_LOG_ENABLED`, default on, independent of
   `ACP_TRACE_ENABLED` — events are recorded even when stderr capture is off
   (the run dir is created by whichever writer fires first). Add `/runs` and
   `/runs/{run_id}/events` so history survives refresh/restart. Live path
   stays the ring/SSE.
3. **W2 — The UI**: static vanilla HTML+JS page(s) served by the FastAPI app
   at `GET /` — no build step, no Node toolchain. Live stream view (SSE
   client), per-run trace view (full event list with client-side kind
   filters/collapse — collapsed-by-default for chunk-y kinds like
   `user_message_chunk` echoes and thought chunks), webhook deliveries view.
   Still listener-local.

**W3 (owner-gated, optional)** — exposure: dashboard token auth + a Caddy
route, if remote (non-tunnel) access is ever wanted.

## Options

### Option A — FastAPI-served static page + widened contract + JSONL history (recommended)

Vanilla HTML/JS like the old repo's `static/*.html`; no new toolchain; every
phase is small and independently landable; complexity stays well under the
threshold that parked this in the first place.

### Option B — Vite SPA (the `python-uv-fastapi-vite` app-stack profile)

Richer UX if the UI ever grows controls; costs a Node build chain wired into a
Python service's CI/compose for what is an internal observability page.
Revisit only if the UI outgrows Option A.

### Option C — Blazor WASM (SwarmSandbox.Web precedent)

A .NET front end onto a Python listener — the precedent is a separate .NET
service with its own backend. Not a fit here.

## Decisions (owner-folded 2026-10-15)

All four open questions were taken as recommended; the events log also gets
its own enable flag rather than riding `ACP_TRACE_ENABLED`:

1. **v1 scope** — all three views: live feed + run history + webhook
   deliveries (they fall out of the same store/log).
2. **Persistence** — per-run JSONL files, anchored to the `trace_log`
   conventions per W1 above (`ACP_TRACE_ROOT` run dir, `ACP_TRACE_KEEP_RUNS`
   retention, best-effort posture).
3. **Exposure** — listener-local/SSH-tunnel for v1; posture unchanged, no
   auth surface. Token auth + a Caddy route stays W3, owner-gated.
4. **Chunk-y kinds** — `user_message_chunk` and `agent_thought_chunk` are
   forwarded verbatim (consistent with ALL-traces); the UI collapses them by
   default. No server-side truncation.

## Non-goals

- Control-plane actions from the UI (cancel, replay, enqueue) — observation
  only for now.
- Porting old-stack surfaces: beads, bvr pages, graph, the stderr narrative.
- Replacing or extending `SwarmSandbox.Web`.
- Tailing the agent's (redacted) stderr capture into the UI — the ACP stream
  is the trace source per Decision 7.
- Queue/EventStore durability beyond the JSONL event log (GitHub redelivery
  remains the recovery path per the PromptInfo design's no-durability
  posture).

## Validation

Every phase PR runs the full `validation.ps1` gate (build → scan → test;
coverage stays > 85%). W0's mapping is unit-tested through the duck-typed
client callbacks (all 13 kinds + one synthetic unknown kind); the SSE tests
bind a real uvicorn on an ephemeral port (starlette TestClient deadlocks on
infinite SSE — house gotcha). The e2e simulator's `/events` assertions grow
with any new event names it can observe.
