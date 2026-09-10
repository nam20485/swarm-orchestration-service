"""Tests for the PromptInfo envelope, the PromptQueue, and the Phase 1 wiring."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from webhook_receiver.app import create_app
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.github import compute_signature
from webhook_receiver.prompt_queue import PromptInfo, PromptQueue

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"

VALID_PAYLOAD = {
    "action": "labeled",
    "sender": {"login": "nam20485"},
    "label": {"name": "orchestration:plan"},
    "issue": {"number": 1, "labels": [{"name": "orchestration:plan"}]},
    "repository": {"full_name": "owner/repo"},
}


def make_settings() -> Settings:
    return Settings(
        host="testserver",
        port=80,
        github_webhook_secret=SECRET,
        max_body_bytes=25 * 1024 * 1024,
        log_level="info",
    )


def make_info(delivery_id: str = "d-1", **overrides: object) -> PromptInfo:
    fields: dict[str, object] = {
        "delivery_id": delivery_id,
        "repo": "owner/repo",
        "event": "issues",
        "action": "labeled",
        "label": "orchestration:plan",
        "payload": dict(VALID_PAYLOAD),
    }
    fields.update(overrides)
    return PromptInfo(**fields)  # type: ignore[arg-type]


def post(
    client: TestClient,
    payload: dict,
    delivery_id: str = "d-123",
    event: str = "issues",
) -> object:
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": compute_signature(body, SECRET),
        },
    )


def events_of_type(store: EventStore, type_: str) -> list[dict]:
    return [e for e in store.recent() if e["type"] == type_]


async def drain(q: PromptQueue) -> None:
    """Run the consumer until the queue is empty, then cancel it cleanly."""
    task = asyncio.create_task(q.consume())
    await q._queue.join()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class TestPromptInfoEnvelope:
    def test_delivery_id_required(self) -> None:
        with pytest.raises(ValidationError):
            PromptInfo(
                repo="owner/repo",
                event="issues",
                action="labeled",
                label="orchestration:plan",
                payload={},
            )

    def test_frozen_after_construction(self) -> None:
        info = make_info()
        with pytest.raises(ValidationError):
            info.delivery_id = "d-2"  # type: ignore[misc]

    def test_default_ids_unique(self) -> None:
        assert make_info().id != make_info().id

    def test_defaults_per_design_table(self) -> None:
        info = make_info()
        assert info.source == "github_webhook"
        assert info.prompt is None
        assert info.priority == 0
        assert info.status == "queued"
        assert info.consumed_at is None
        assert info.enqueued_at > 0

    def test_literal_fields_validated(self) -> None:
        with pytest.raises(ValidationError):
            make_info(source="cron")
        with pytest.raises(ValidationError):
            make_info(status="running")


class TestPromptQueueDedup:
    def test_new_delivery_accepted_duplicate_dropped(self) -> None:
        store = EventStore()
        q = PromptQueue(store)
        assert q.enqueue(make_info("d-1")) is True
        assert q.enqueue(make_info("d-1")) is False
        assert q._queue.qsize() == 1

    def test_eviction_frees_delivery_id(self) -> None:
        q = PromptQueue(EventStore(), dedup_capacity=2)
        assert q.enqueue(make_info("d-1")) is True
        assert q.enqueue(make_info("d-2")) is True
        assert q.enqueue(make_info("d-3")) is True  # evicts d-1
        assert q.enqueue(make_info("d-2")) is False  # still within window
        assert q.enqueue(make_info("d-1")) is True  # evicted -> accepted again

    def test_duplicate_not_reregistered(self) -> None:
        # A dropped duplicate must not refresh its dedup window position:
        # with capacity 2, d-1 must still be the oldest entry when d-3 lands.
        q = PromptQueue(EventStore(), dedup_capacity=2)
        q.enqueue(make_info("d-1"))
        q.enqueue(make_info("d-2"))
        assert q.enqueue(make_info("d-1")) is False  # duplicate: no re-register
        q.enqueue(make_info("d-3"))  # evicts d-1 (oldest), not d-2
        assert q.enqueue(make_info("d-1")) is True


class TestPromptQueueConsumer:
    def test_drains_fifo_in_enqueue_order(self) -> None:
        store = EventStore()
        q = PromptQueue(store)
        for did in ("d-1", "d-2", "d-3"):
            q.enqueue(make_info(did))

        asyncio.run(drain(q))

        consumed = events_of_type(store, "prompt_consumed")
        assert [e["data"]["delivery_id"] for e in consumed] == ["d-1", "d-2", "d-3"]
        assert all(e["data"]["ok"] is True for e in consumed)
        assert q._queue.qsize() == 0

    def test_consumed_event_carries_envelope_identity(self) -> None:
        store = EventStore()
        q = PromptQueue(store)
        info = make_info("d-1")
        q.enqueue(info)

        asyncio.run(drain(q))

        # The queued envelope itself stays frozen at its queued state.
        assert info.status == "queued"
        assert info.consumed_at is None
        consumed = events_of_type(store, "prompt_consumed")
        assert consumed[0]["data"]["id"] == info.id
        assert consumed[0]["data"]["repo"] == "owner/repo"
        assert consumed[0]["data"]["label"] == "orchestration:plan"

    def test_failure_records_ok_false_without_retry(self) -> None:
        class FailingStore(EventStore):
            def emit(self, event_type: str, **data: object) -> None:
                if event_type == "prompt_consumed" and data.get("ok") is True:
                    raise RuntimeError("boom")
                super().emit(event_type, **data)

        store = FailingStore()
        q = PromptQueue(store)
        q.enqueue(make_info("d-1"))

        asyncio.run(drain(q))

        consumed = events_of_type(store, "prompt_consumed")
        assert len(consumed) == 1
        assert consumed[0]["data"]["ok"] is False
        assert consumed[0]["data"]["delivery_id"] == "d-1"
        assert q._queue.qsize() == 0


class TestWebhookQueueWiring:
    def test_accepted_delivery_queued_and_consumed_via_lifespan(self) -> None:
        store = EventStore()
        with TestClient(create_app(make_settings(), store)) as client:
            resp = post(client, VALID_PAYLOAD)
            assert resp.status_code == 202
            assert resp.json() == {
                "status": "accepted",
                "delivery_id": "d-123",
                "event": "issues",
            }

            # The lifespan-started consumer drains the queue on its own loop.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not events_of_type(
                store, "prompt_consumed"
            ):
                time.sleep(0.01)

        assert len(events_of_type(store, "prompt_queued")) == 1
        assert len(events_of_type(store, "prompt_consumed")) == 1

    def test_redelivered_delivery_recorded_duplicate_not_requeued(self) -> None:
        store = EventStore()
        queue = PromptQueue(store)
        client = TestClient(create_app(make_settings(), store, prompt_queue=queue))

        first = post(client, VALID_PAYLOAD)
        second = post(client, VALID_PAYLOAD)

        # Contract unchanged: both deliveries ack 202 accepted.
        assert first.status_code == 202
        assert second.status_code == 202
        assert second.json()["status"] == "accepted"
        assert queue._queue.qsize() == 1
        queued = events_of_type(store, "prompt_queued")
        duplicates = events_of_type(store, "webhook_duplicate")
        assert len(queued) == 1
        assert queued[0]["data"]["delivery_id"] == "d-123"
        assert len(duplicates) == 1
        assert duplicates[0]["data"]["delivery_id"] == "d-123"

    def test_filtered_delivery_never_queued(self) -> None:
        store = EventStore()
        queue = PromptQueue(store)
        client = TestClient(create_app(make_settings(), store, prompt_queue=queue))

        payload = dict(VALID_PAYLOAD, label={"name": "bug"})
        payload["issue"] = {"number": 1, "labels": [{"name": "bug"}]}
        resp = post(client, payload)

        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"
        assert queue._queue.qsize() == 0
        assert events_of_type(store, "prompt_queued") == []
        assert events_of_type(store, "webhook_duplicate") == []

    def test_ping_delivery_never_queued(self) -> None:
        store = EventStore()
        queue = PromptQueue(store)
        client = TestClient(create_app(make_settings(), store, prompt_queue=queue))

        resp = post(client, {}, event="ping")

        assert resp.status_code == 200
        assert queue._queue.qsize() == 0
        assert events_of_type(store, "prompt_queued") == []
