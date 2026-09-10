"""Endpoint tests for the /webhooks/github verify -> gate -> store path."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from webhook_receiver.app import create_app
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore
from webhook_receiver.github import compute_signature
from webhook_receiver.prompt_queue import PromptQueue

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"

VALID_PAYLOAD = {
    "action": "labeled",
    "sender": {"login": "nam20485"},
    "label": {"name": "orchestration:plan"},
    "issue": {"number": 1, "labels": [{"name": "orchestration:plan"}]},
    "repository": {"full_name": "owner/repo"},
}


def make_settings(max_body_bytes: int = 25 * 1024 * 1024) -> Settings:
    return Settings(
        host="testserver",
        port=80,
        github_webhook_secret=SECRET,
        max_body_bytes=max_body_bytes,
        log_level="info",
    )


def post(
    client: TestClient,
    payload: dict | bytes,
    event: str = "issues",
    signature: str | None = None,
) -> object:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "X-GitHub-Delivery": "d-123"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhooks/github", content=body, headers=headers)


@pytest.fixture()
def store() -> EventStore:
    return EventStore()


@pytest.fixture()
def client(store: EventStore) -> TestClient:
    return TestClient(create_app(make_settings(), store))


def signed(body: bytes) -> str:
    return compute_signature(body, SECRET)


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSignatureRejection:
    def test_bad_signature_rejected_401(self, client: TestClient) -> None:
        resp = post(client, VALID_PAYLOAD, signature=signed(b"tampered"))
        assert resp.status_code == 401

    def test_missing_signature_rejected_401(self, client: TestClient) -> None:
        resp = post(client, VALID_PAYLOAD, signature=None)
        assert resp.status_code == 401

    def test_valid_signature_ping_pongs_200(self, client: TestClient) -> None:
        resp = post(client, b"{}", event="ping", signature=signed(b"{}"))
        assert resp.status_code == 200
        assert resp.json() == {"status": "pong", "delivery_id": "d-123"}


class TestVerifyGateStorePath:
    def test_accepted_delivery_stored(self, client: TestClient, store: EventStore) -> None:
        resp = post(client, VALID_PAYLOAD, signature=signed(json.dumps(VALID_PAYLOAD).encode()))
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"
        types = [e["type"] for e in store.recent()]
        assert "webhook_received" in types
        assert "webhook_accepted" in types
        assert "webhook_filtered" not in types

    def test_non_workflow_label_filtered(self, client: TestClient, store: EventStore) -> None:
        payload = dict(VALID_PAYLOAD, label={"name": "bug"})
        payload["issue"] = {"number": 1, "labels": [{"name": "bug"}]}
        resp = post(client, payload, signature=signed(json.dumps(payload).encode()))
        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"
        types = [e["type"] for e in store.recent()]
        assert "webhook_filtered" in types
        assert "webhook_accepted" not in types

    def test_bot_sender_filtered(self, client: TestClient, store: EventStore) -> None:
        payload = dict(VALID_PAYLOAD, sender={"login": "github-actions[bot]"})
        resp = post(client, payload, signature=signed(json.dumps(payload).encode()))
        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"

    def test_wrong_event_filtered(self, client: TestClient, store: EventStore) -> None:
        resp = post(client, VALID_PAYLOAD, event="push", signature=signed(json.dumps(VALID_PAYLOAD).encode()))
        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"

    def test_invalid_json_with_valid_signature_400(self, client: TestClient) -> None:
        resp = post(client, b"{not json", signature=signed(b"{not json"))
        assert resp.status_code == 400

    def test_oversized_body_413(self, store: EventStore) -> None:
        tiny = TestClient(create_app(make_settings(max_body_bytes=10), store))
        body = b"x" * 100
        resp = post(tiny, body, signature=signed(body))
        assert resp.status_code == 413

    def test_oversized_body_checked_before_signature(self, store: EventStore) -> None:
        # 413 takes precedence over signature verification (matches old repo).
        tiny = TestClient(create_app(make_settings(max_body_bytes=10), store))
        resp = post(tiny, b"x" * 100, signature="sha256=00")
        assert resp.status_code == 413


class RecordingQueue(PromptQueue):
    """Queue that remembers enqueued envelopes for assertions."""

    def __init__(self, store: EventStore) -> None:
        super().__init__(store)
        self.enqueued: list = []

    def enqueue(self, info) -> bool:
        self.enqueued.append(info)
        return super().enqueue(info)


class TestEnqueuedPrompt:
    """Phase 3: the accepted path fills the envelope's orchestration prompt."""

    def _client_for(self, store: EventStore) -> tuple[TestClient, RecordingQueue]:
        queue = RecordingQueue(store)
        return TestClient(create_app(make_settings(), store, prompt_queue=queue)), queue

    def test_accepted_delivery_enqueues_orchestration_prompt(
        self, store: EventStore
    ) -> None:
        client, queue = self._client_for(store)
        resp = post(client, VALID_PAYLOAD, signature=signed(json.dumps(VALID_PAYLOAD).encode()))
        assert resp.status_code == 202
        info = queue.enqueued[0]
        assert info.prompt is not None
        assert "owner/repo" in info.prompt
        assert "orchestration:plan" in info.prompt
        assert "live tracking state" in info.prompt

    def test_direct_body_enqueues_body_verbatim(self, store: EventStore, monkeypatch) -> None:
        monkeypatch.setenv("DIRECT_BODY_ALLOWED_SENDERS", "nam20485")
        payload = dict(VALID_PAYLOAD, label={"name": "gh-issue-tracking:direct-body"})
        payload["issue"] = dict(
            payload["issue"],
            labels=[{"name": "gh-issue-tracking:direct-body"}],
            body="do the thing",
        )
        client, queue = self._client_for(store)
        resp = post(client, payload, signature=signed(json.dumps(payload).encode()))
        assert resp.status_code == 202
        assert queue.enqueued[0].prompt == "do the thing"

    def test_filtered_delivery_enqueues_nothing(self, store: EventStore) -> None:
        client, queue = self._client_for(store)
        payload = dict(VALID_PAYLOAD, label={"name": "bug"})
        resp = post(client, payload, signature=signed(json.dumps(payload).encode()))
        assert resp.status_code == 202
        assert queue.enqueued == []
