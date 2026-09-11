"""GET /events SSE tests: replay, live fan-out, keepalive, disconnect cleanup.

The stream is infinite, so starlette's TestClient (which runs the ASGI app
to completion and buffers the body) cannot exercise it; these tests bind a
real uvicorn server on an ephemeral loopback port instead.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn

from webhook_receiver.app import _sse_frame, create_app
from webhook_receiver.config import Settings
from webhook_receiver.event_store import EventStore

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"


def make_settings(keepalive: float = 0.1) -> Settings:
    return Settings(
        host="testserver",
        port=80,
        github_webhook_secret=SECRET,
        max_body_bytes=25 * 1024 * 1024,
        log_level="info",
        events_keepalive=keepalive,
    )


def start_server(store: EventStore) -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(
        create_app(make_settings(), store),
        host="127.0.0.1",
        port=0,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("uvicorn server did not start within 10s")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


def stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


class FrameReader:
    """Accumulates SSE frames from ``iter_lines`` output."""

    def __init__(self) -> None:
        self.frames: list[dict[str, str]] = []
        self.comments = 0
        self._current: dict[str, str] = {}

    def feed(self, line: str) -> None:
        if line.startswith(":"):
            self.comments += 1
            return
        if not line:
            if self._current:
                self.frames.append(self._current)
                self._current = {}
            return
        field, _, value = line.partition(":")
        self._current[field.strip()] = value.strip()

    @property
    def types(self) -> list[str]:
        return [f.get("event", "") for f in self.frames]


@pytest.fixture()
def sse_server() -> Iterator[tuple[EventStore, str]]:
    store = EventStore()
    server, thread, port = start_server(store)
    try:
        yield store, f"http://127.0.0.1:{port}"
    finally:
        stop_server(server, thread)


class TestSseFrame:
    def test_frame_encodes_store_event(self) -> None:
        event = {"id": 7, "type": "prompt_queued", "data": {"delivery_id": "d-1"}}
        assert _sse_frame(event) == (
            'id: 7\nevent: prompt_queued\ndata: {"delivery_id":"d-1"}\n\n'
        )

    def test_none_yields_keepalive_comment(self) -> None:
        assert _sse_frame(None) == ": keepalive\n\n"


class TestEventsEndpoint:
    def test_replays_history_then_streams_live(
        self, sse_server: tuple[EventStore, str]
    ) -> None:
        store, base_url = sse_server
        store.emit("webhook_received", delivery_id="d-1", event="issues")
        store.emit("webhook_accepted", delivery_id="d-1", event="issues", label="x")

        def emit_later() -> None:
            time.sleep(0.5)
            store.emit("prompt_queued", id="env-1", delivery_id="d-1")

        thread = threading.Thread(target=emit_later)
        reader = FrameReader()
        thread.start()
        try:
            with httpx.Client() as client:
                with client.stream("GET", f"{base_url}/events") as response:
                    assert response.status_code == 200
                    assert response.headers["content-type"].startswith(
                        "text/event-stream"
                    )
                    assert response.headers["cache-control"] == "no-cache"
                    for line in response.iter_lines():
                        reader.feed(line)
                        if reader.types and reader.types[-1] == "prompt_queued":
                            break
        finally:
            thread.join()

        assert reader.types == [
            "webhook_received",
            "webhook_accepted",
            "prompt_queued",
        ]
        assert reader.frames[0]["id"] == "1"
        assert json.loads(reader.frames[2]["data"]) == {
            "id": "env-1",
            "delivery_id": "d-1",
        }
        # Idle while waiting for the live event: keepalives must flow.
        assert reader.comments >= 1

    def test_disconnect_deregisters_subscriber(
        self, sse_server: tuple[EventStore, str]
    ) -> None:
        store, base_url = sse_server
        with httpx.Client() as client:
            with client.stream("GET", f"{base_url}/events") as response:
                assert response.status_code == 200
                for _ in response.iter_lines():
                    break  # abort as soon as the response is established
        deadline = time.monotonic() + 5
        while store.subscriber_count > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert store.subscriber_count == 0
