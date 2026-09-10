from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.filters import should_dispatch
from webhook_receiver.github import verify_signature

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    event_store: EventStore | None = None,
) -> FastAPI:
    """Build the webhook listener app (port of orchestrator-service @2bd6d06).

    Phase 0.0 scope: HMAC verification, the dispatch gate, and EventStore
    logging. Dispatch itself is stubbed — Phase 1 replaces the old
    BackgroundTasks+Popen path with a PromptInfo enqueue (see TODO below).
    """
    cfg = settings or Settings.from_env()
    store = event_store or EventStore()
    app = FastAPI(
        title="Swarm Orchestration GitHub Webhook Receiver",
        version="0.1.0",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

        # TODO(Phase 1): construct a PromptInfo from (event, payload) and
        # enqueue it on the async PromptInfo queue; a consumer hands it to the
        # ACP host (Phase 2). The old BackgroundTasks + subprocess.Popen
        # dispatch to opencode is deliberately NOT ported — see
        # docs/plans/orchestrator-service-simplification.md §7 Phase 1/Phase 2.
        logger.info(
            "Accepted delivery_id=%s event=%s action=%s (dispatch stubbed: "
            "PromptInfo queue lands in Phase 1)",
            delivery_id,
            event,
            payload.get("action"),
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
