"""Webhook listener app: verify → gate → queue → dashboard event surface.

HTTP surface (Caddy exposes only ``/webhooks/github`` and ``/health``; the
dashboard endpoints below are listener-local, reachable on the internal
network or via an SSH/compose tunnel):

- ``POST /webhooks/github`` — GitHub App deliveries: HMAC-verified, gated
  (``filters.should_dispatch``), deduped, and enqueued as a PromptInfo.
- ``GET /health`` — liveness probe.
- ``GET /events`` — SSE stream (``text/event-stream``) of the EventStore:
  full ring-buffer replay on subscribe, then live fan-out; a ``: keepalive``
  comment is emitted after ``WEBHOOK_EVENTS_KEEPALIVE`` idle seconds. Each
  frame carries the store's monotonic ``id``, the event ``type``, and the
  event data as a JSON ``data`` line.
- ``GET /`` — the observability page (webui plan W2): static HTML+JS,
  no build step — live feed over the SSE endpoint, run history with full
  per-run traces, and the durable webhook tail. Listener-local.
- ``GET /events/history`` — durable global tail (rotated root-level
  ``events.jsonl`` pair, oldest first) — pre-envelope webhook events that
  survive restarts, unlike the ring.
- ``GET /runs`` / ``GET /runs/{run_id}/events`` — durable run history from
  the events JSONL tail (webui plan W1, ``WEBHOOK_EVENTS_LOG_ENABLED``):
  index of runs under ``ACP_TRACE_ROOT`` (newest first, manifests merged),
  and the full per-run event list that survives restarts and ring churn.

**Stable event names** (dashboard contract — additive changes only; this
table is the single source of truth, mirrored by ``src/webhook_receiver/
README.md``). ``run_id`` is the PromptInfo ``id``; ``delivery_id`` is
GitHub's ``X-GitHub-Delivery``:

=========================  ================================================
Event type                 Data
=========================  ================================================
``webhook_received``       delivery_id, event, action, repo
``webhook_filtered``       delivery_id, event, action, reason
``webhook_accepted``       delivery_id, event, action, repo, sender, label
``prompt_queued``          id, delivery_id, repo, event, action, label
``prompt_consumed``        id, delivery_id, ok; on success also repo,
                           event, action, label, session_id, stop_reason;
                           on failure instead error
``webhook_duplicate``      delivery_id, event, action
``sandbox_provisioned``    run_id, sandbox_id, container_name, workspace
``sandbox_released``       run_id, sandbox_id, ok
``user_message_chunk``     run_id, text (the dispatch prompt echo)
``agent_session_started``  run_id, session_id, protocol_version
``agent_message_chunk``    run_id, text
``agent_thought_chunk``    run_id, text
``agent_tool_call``        run_id, tool_call_id, title, kind, status
``agent_plan``             run_id, entries (full plan snapshot)
``agent_plan_update``      run_id, plan (items/file/markdown delta, wire names)
``agent_plan_removed``     run_id, plan_id
``agent_commands_update``  run_id, commands (available-commands list)
``agent_mode_update``      run_id, mode_id
``agent_session_info``     run_id, title, updated_at
``agent_config_update``    run_id, options (config-option list, wire names)
``agent_update``           run_id, kind, payload (unrecognized kinds)
``agent_usage``            run_id, used, size, cost
``agent_permission``       run_id, title, action, reason
``agent_finished``         run_id, session_id, stop_reason, ok,
                           error (failures only)
=========================  ================================================

Emitter sources: the webhook routes here (``webhook_*``), the queue consumer
(``prompt_*``, see ``prompt_queue.py``), the SwarmSandbox bridge
(``sandbox_*``, see ``sandbox_bridge.py``), and the ACP host session mapping
(``agent_*`` + ``user_message_chunk``, see ``acp_host.py`` — ALL-traces: every
``session/update`` kind maps, unknown kinds pass through as ``agent_update``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from webhook_receiver.acp_host import AcpHost
from webhook_receiver.config import Settings
from webhook_receiver.event_log import (
    EventLog,
    list_runs,
    read_global_tail,
    read_run_events,
)
from webhook_receiver.event_store import EventStore
from webhook_receiver.filters import should_dispatch
from webhook_receiver.github import verify_signature
from webhook_receiver.prompt_builder import build_orchestration_prompt
from webhook_receiver.prompt_queue import PromptInfo, PromptQueue
from webhook_receiver.trace_log import resolve_trace_root

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _sse_frame(item: dict[str, Any] | None) -> str:
    """Format one EventStore entry (or keepalive ``None``) as an SSE frame."""
    if item is None:
        return ": keepalive\n\n"
    data = json.dumps(item["data"], separators=(",", ":"))
    return f"id: {item['id']}\nevent: {item['type']}\ndata: {data}\n\n"


def create_app(
    settings: Settings | None = None,
    event_store: EventStore | None = None,
    prompt_queue: PromptQueue | None = None,
) -> FastAPI:
    """Build the webhook listener app (port of orchestrator-service @2bd6d06).

    Accepted deliveries are enqueued as frozen PromptInfo envelopes (deduped
    by delivery id) and drained by a consumer task started in the app
    lifespan. Phase 2: when the app owns the queue and ``acp_enabled`` is
    set, the consumer drives the ACP host — one cold opencode session per
    envelope. An injected ``prompt_queue`` keeps its own host (tests and
    host variants wire their own); with ACP disabled the consumer falls back
    to the Phase 1 mark-consumed placeholder. The same ownership applies to
    an injected ``event_store``: it keeps its own sink wiring (or none) —
    the durable events tail is attached only to the default-constructed
    store, whose construction this function owns.
    """
    cfg = settings or Settings.from_env()
    sink = (
        EventLog(
            resolve_trace_root(cfg.acp_trace_root),
            keep_runs=cfg.acp_trace_keep_runs,
        ).append
        if cfg.events_log_enabled
        else None
    )
    store = event_store or EventStore(maxlen=cfg.events_maxlen, sink=sink)
    queue = prompt_queue or PromptQueue(
        store, host=AcpHost(cfg, store) if cfg.acp_enabled else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        consumer = asyncio.create_task(
            queue.consume(), name="prompt-queue-consumer"
        )
        try:
            yield
        finally:
            consumer.cancel()
            with suppress(asyncio.CancelledError):
                await consumer

    app = FastAPI(
        title="Swarm Orchestration GitHub Webhook Receiver",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/events")
    async def events() -> StreamingResponse:
        """Stream the EventStore to the dashboard over SSE.

        The subscriber's blocking ``next`` runs one call at a time on the
        loop's default thread pool, so a slow dashboard client never blocks
        the event loop; on disconnect the async generator's ``finally``
        deregisters the subscriber immediately (a straggling pool thread
        wakes within one keepalive and exits harmlessly). Each connected
        client holds one pool thread while idle — the dashboard audience is
        small by design.
        """
        subscriber = store.subscribe(keepalive=cfg.events_keepalive)

        async def stream() -> AsyncIterator[str]:
            try:
                while True:
                    item = await asyncio.to_thread(subscriber.__next__)
                    yield _sse_frame(item)
            finally:
                subscriber.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """Observability page (webui plan W2): live SSE feed, run history,
        and the durable webhook tail — one static HTML file, no build step,
        no dependencies. Listener-local like every dashboard endpoint."""
        # no-cache: the page is one small file; an updated UI must never
        # hide behind a 304-revalidated stale copy (bitten the owner twice).
        return FileResponse(
            _STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/events/history")
    async def events_history() -> list[dict[str, Any]]:
        """Durable global tail (webui plan W2): pre-envelope webhook events
        from the rotated root-level events.jsonl pair, oldest first. The
        webhooks view filters these client-side; survives restarts unlike
        the ring. Offloaded like the run-events read — a fully-rotated
        tail must never stall the loop."""
        return await asyncio.to_thread(read_global_tail, cfg.acp_trace_root)

    @app.get("/runs")
    async def runs() -> list[dict[str, Any]]:
        """Run history index (webui plan W1): run directories under the trace
        root that carry an ``events.jsonl``, newest first, each merged with
        its ``manifest.json`` when present. Listener-local like ``/events``;
        empty when the events log is off or nothing ran yet."""
        return list_runs(cfg.acp_trace_root)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str) -> list[dict[str, Any]]:
        """Full per-run event history from ``events.jsonl``, oldest first —
        the durable counterpart of the ring replay. 404 for an unknown run
        or a malformed run id."""
        # Offloaded like /events' blocking work: a long run's tail must
        # never stall the loop (and through it, webhook handling).
        events = await asyncio.to_thread(
            read_run_events, cfg.acp_trace_root, run_id
        )
        if events is None:
            raise HTTPException(
                status_code=404, detail=f"No event history for run {run_id!r}"
            )
        return events

    @app.post(
        "/webhooks/github",
        status_code=202,
        responses={
            200: {"description": "Ping event acknowledged (pong)."},
            202: {
                "description": (
                    "Webhook delivery accepted, or filtered/ignored without "
                    "dispatch (non-matching label, bot actor, etc.)."
                )
            },
            400: {"description": "Invalid JSON body."},
            401: {"description": "Invalid signature."},
            413: {"description": "Request body too large."},
        },
    )
    async def github_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event = request.headers.get("X-GitHub-Event", "").lower()
        signature = request.headers.get("X-Hub-Signature-256")

        if len(body) > cfg.max_body_bytes:
            logger.warning(
                "Rejected webhook delivery_id=%s event=%s (body too large: %s bytes)",
                delivery_id,
                event,
                len(body),
            )
            raise HTTPException(status_code=413, detail="Request body too large")

        if not verify_signature(body, signature, cfg.github_webhook_secret):
            logger.warning(
                "Rejected webhook delivery_id=%s event=%s (bad signature)",
                delivery_id,
                event,
            )
            raise HTTPException(status_code=401, detail="Invalid signature")

        if event == "ping":
            return JSONResponse(
                {"status": "pong", "delivery_id": delivery_id},
                status_code=200,
            )

        try:
            payload: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

        logger.info(
            "Webhook received delivery_id=%s event=%s action=%s repo=%s sender=%s",
            delivery_id,
            event,
            payload.get("action"),
            payload.get("repository", {}).get("full_name", "?"),
            payload.get("sender", {}).get("login", "?"),
        )

        store.emit(
            "webhook_received",
            delivery_id=delivery_id,
            event=event,
            action=payload.get("action", ""),
            repo=payload.get("repository", {}).get("full_name", "?"),
        )

        # Transport-level dispatch gate. Only ``issues.labeled`` by a non-bot
        # actor with a workflow-relevant label may dispatch the agent;
        # anything else is acknowledged but not dispatched, preventing the
        # echo-loop where a bot-posted comment re-triggers itself.
        allow, reason = should_dispatch(event, payload)
        if not allow:
            logger.info(
                "Filtered delivery_id=%s event=%s action=%s reason=%s",
                delivery_id,
                event,
                payload.get("action"),
                reason,
            )
            store.emit(
                "webhook_filtered",
                delivery_id=delivery_id,
                event=event,
                action=payload.get("action", ""),
                reason=reason,
            )
            return JSONResponse(
                {
                    "status": "ignored",
                    "delivery_id": delivery_id,
                    "event": event,
                    "reason": reason,
                },
                status_code=202,
            )

        store.emit(
            "webhook_accepted",
            delivery_id=delivery_id,
            event=event,
            action=payload.get("action", ""),
            repo=payload.get("repository", {}).get("full_name", "?"),
            sender=payload.get("sender", {}).get("login", "?"),
            label=(payload.get("label") or {}).get("name", ""),
        )

        repo_full = payload.get("repository", {}).get("full_name", "?")
        action = payload.get("action", "")
        label_name = (payload.get("label") or {}).get("name", "")

        info = PromptInfo(
            delivery_id=delivery_id,
            repo=repo_full,
            event=event,
            action=action,
            label=label_name,
            payload=payload,
        )
        # Phase 3: fill the envelope's orchestration prompt at enqueue time
        # (docs/plans/completed/promptinfo-design.md §2) — the ACP host's prompt seam
        # sends a filled envelope prompt verbatim instead of deriving one.
        info = info.model_copy(update={"prompt": build_orchestration_prompt(info)})
        if queue.enqueue(info):
            logger.info(
                "Accepted delivery_id=%s event=%s action=%s (queued PromptInfo id=%s)",
                delivery_id,
                event,
                action,
                info.id,
            )
            store.emit(
                "prompt_queued",
                id=info.id,
                delivery_id=delivery_id,
                repo=repo_full,
                event=event,
                action=action,
                label=label_name,
            )
        else:
            logger.info(
                "Duplicate delivery_id=%s event=%s dropped by queue dedup",
                delivery_id,
                event,
            )
            store.emit(
                "webhook_duplicate",
                delivery_id=delivery_id,
                event=event,
                action=action,
            )
        return JSONResponse(
            {
                "status": "accepted",
                "delivery_id": delivery_id,
                "event": event,
            },
            status_code=202,
        )

    return app
