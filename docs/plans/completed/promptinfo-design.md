# PromptInfo Queue — Design (Phase 0.2)

Status: DESIGNED per [`orchestrator-service-simplification.md`](./orchestrator-service-simplification.md) §5 Decisions 1–2 and §3.1; implementation lands in Phase 1.
Date: 2026-09-10

## 1. Purpose

`PromptInfo` is the typed envelope that carries one accepted webhook delivery from the listener to whatever executes it (Phase 1: the existing dispatch path, unchanged behavior; Phase 2: the ACP host). Today no such thing exists — the old repo handed off via `BackgroundTasks` + `subprocess.Popen` (plan §2). The queue is the seam that lets Phase 2 replace the consumer without touching the listener.

## 2. Envelope (typed, export-ready)

Pydantic v2 model (the service already depends on FastAPI/pydantic), frozen after construction:

| Field | Type | Notes |
|---|---|---|
| `id` | `str` (uuid4 hex) | envelope identity; independent of GitHub so non-webhook sources fit later |
| `source` | `Literal["github_webhook"]` | extensible union when new sources appear |
| `delivery_id` | `str` | GitHub `X-GitHub-Delivery` — the dedup key |
| `repo` | `str` | `repository.full_name` |
| `event` / `action` / `label` | `str` / `str` / `str` | gate context (`issues` / `labeled` / workflow label) |
| `payload` | `dict` | the parsed delivery body, bounded upstream by the existing 413 size cap |
| `prompt` | `str \| None` | Phase 1 leaves `None` (pointer semantics); Phase 3's orchestration-prompt build fills it |
| `priority` | `int = 0` | **reserved** — FIFO substrate ignores it; survives export to a priority-capable store |
| `status` | `Literal["queued", "consumed"]` | queue-owned lifecycle only; downstream states are the consumer's business |
| `enqueued_at` / `consumed_at` | `float` | monotonic timestamps |

Design intent (Decision 2): every field maps 1:1 onto a Redis-stream / sqlite-row entry, so a later substrate swap changes queue internals only — never the envelope shape or the listener.

## 3. Substrate: in-process `asyncio.Queue`

Single queue created at app startup (lifespan), unbounded, one consumer task. Rationale (Decision 2): matches the single-container deployment, zero new dependencies; durability deferred (§5). No Redis, no streams, no sqlite in Phase 1.

**Dedup:** bounded registry of seen `delivery_id`s (deque + set, last 1024). GitHub redelivers (at-least-once), so a duplicate `delivery_id` → drop + `webhook_duplicate` store event, 202 to GitHub as usual. The registry bounds memory; 1024 ids comfortably exceeds GitHub's redelivery window.

## 4. EventStore relationship: separate, fed by lifecycle events

The queue is **not** the EventStore — the store stays the dashboard/SSE concern (plan §3.1, and the ported `event_store.py` header says the same). The queue emits lifecycle events into it: `prompt_queued`, `prompt_consumed`, `webhook_duplicate` — exactly the event names in plan §7 Phase 1's exit criteria.

## 5. Durability posture (explicit)

**None in Phase 1.** A process restart drops unconsumed envelopes. Accepted because:

1. GitHub retains every delivery and supports redelivery (UI or REST `POST /repos/{owner}/{repo}/deliveries/{id}/attempts`) — the manual recovery path for anything missed.
2. Persistence gets added the day a missed webhook actually hurts (Decision 2) — the export-ready envelope (§2) is the preparation for that day.

## 6. Consumer contract

- **Phase 1:** consumer dequeues and adapts into the *existing* dispatch path (behavior-preserving; plan §7 Phase 1). On consumer exception: log + `prompt_consumed {ok: false}` store event, item dropped — no retry loop (consistent with §5).
- **Phase 2:** the consumer is replaced by the ACP-host handoff — one cold session per envelope (Decision 4), no host-side model pins (Decision 10).
- Listener-side guarantee: enqueue happens only for deliveries that passed HMAC + the `should_dispatch` gate; the queue never sees filtered traffic.

## 7. Phase 1 test plan (pytest, joins the existing suite)

- Envelope: frozen/immutability, field validation, `delivery_id` required.
- Dedup: second enqueue of the same `delivery_id` dropped, `webhook_duplicate` emitted.
- Ordering: FIFO under burst; consumer drains in order.
- Integration: `webhook_accepted` path enqueues; `prompt_queued`/`prompt_consumed` observable through the EventStore.
