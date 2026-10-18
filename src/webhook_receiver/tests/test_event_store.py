"""EventStore tests: ring buffer, recent(), SSE subscriber fan-out."""

from __future__ import annotations

import time

from webhook_receiver import event_store
from webhook_receiver.event_store import EventStore


class _FakeClock:
    """Stand-in for the ``time`` module with a settable clock."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


class TestEmitAndRecent:
    def test_emit_records_typed_event(self) -> None:
        store = EventStore()
        store.emit("webhook_received", delivery_id="d-1", repo="o/r")
        events = store.recent()
        assert len(events) == 1
        assert events[0]["type"] == "webhook_received"
        assert events[0]["data"]["delivery_id"] == "d-1"
        assert events[0]["data"]["repo"] == "o/r"
        epoch, _, seq = events[0]["id"].partition("-")
        assert epoch.isdigit() and seq == "1"

    def test_ids_increase_monotonically(self) -> None:
        store = EventStore()
        store.emit("a")
        store.emit("b")
        ids = [e["id"] for e in store.recent()]
        assert len(set(ids)) == 2
        (epoch_a, _, seq_a), (epoch_b, _, seq_b) = (i.partition("-") for i in ids)
        assert epoch_a == epoch_b
        assert int(seq_b) == int(seq_a) + 1

    def test_ids_never_collide_across_a_restart(self, monkeypatch) -> None:
        # A UI tab left open across a redeploy dedupes by seen ids; the new
        # process must never reissue an id the old one already used.
        clock = _FakeClock(1_700_000_000.0)
        monkeypatch.setattr(event_store, "time", clock)
        before = EventStore()
        before.emit("a")
        clock.now = 1_700_003_600.0  # an hour later: the restart
        after = EventStore()
        after.emit("a")
        assert before.recent()[0]["id"] != after.recent()[0]["id"]

    def test_recent_limit_returns_last_n(self) -> None:
        store = EventStore()
        for i in range(5):
            store.emit("e", i=i)
        recent = store.recent(limit=2)
        assert [e["data"]["i"] for e in recent] == [3, 4]

    def test_recent_zero_or_negative_limit_is_empty(self) -> None:
        store = EventStore()
        store.emit("e")
        assert store.recent(limit=0) == []
        assert store.recent(limit=-1) == []

    def test_maxlen_ring_buffer_evicts_oldest(self) -> None:
        store = EventStore(maxlen=3)
        for i in range(5):
            store.emit("e", i=i)
        assert [e["data"]["i"] for e in store.recent()] == [2, 3, 4]


class TestSubscribers:
    def test_subscriber_receives_existing_then_new_events(self) -> None:
        store = EventStore()
        store.emit("first")
        sub = store.subscribe(keepalive=0.1)
        store.emit("second")
        assert next(sub)["type"] == "first"
        assert next(sub)["type"] == "second"
        sub.close()

    def test_subscriber_keepalive_yields_none(self) -> None:
        store = EventStore()
        sub = store.subscribe(keepalive=0.05)
        assert next(sub) is None
        sub.close()

    def test_close_deregisters_subscriber(self) -> None:
        store = EventStore()
        sub = store.subscribe(keepalive=0.1)
        assert store.subscriber_count == 1
        sub.close()
        assert store.subscriber_count == 0

    def test_close_is_idempotent(self) -> None:
        store = EventStore()
        sub = store.subscribe(keepalive=0.1)
        sub.close()
        sub.close()
        assert store.subscriber_count == 0

    def test_fan_out_to_multiple_subscribers(self) -> None:
        store = EventStore()
        sub1 = store.subscribe(keepalive=0.1)
        sub2 = store.subscribe(keepalive=0.1)
        store.emit("broadcast", n=1)
        e1 = next(sub1)
        e2 = next(sub2)
        assert e1 == e2
        assert e1["data"]["n"] == 1
        sub1.close()
        sub2.close()

    def test_emit_with_closed_subscribers_does_not_crash(self) -> None:
        store = EventStore()
        sub = store.subscribe(keepalive=0.1)
        sub.close()
        store.emit("after-close")
        assert store.recent()[-1]["type"] == "after-close"
