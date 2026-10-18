from __future__ import annotations

import itertools
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from typing import Any


class Subscriber:
    """Iterator over events from an :class:`EventStore`.

    Created by :meth:`EventStore.subscribe`. Iteration blocks until an event
    arrives or the keepalive timeout expires (yields ``None``). Call
    :meth:`close` to deregister; this is also done via ``__del__``.
    """

    def __init__(
        self,
        store: EventStore,
        q: queue.Queue[dict[str, Any] | None],
        keepalive: float,
    ) -> None:
        self._store = store
        self._q = q
        self._keepalive = keepalive
        self._closed = False

    def __iter__(self) -> Iterator[dict[str, Any] | None]:
        return self

    def __next__(self) -> dict[str, Any] | None:
        if self._closed:
            raise StopIteration
        try:
            return self._q.get(timeout=self._keepalive)
        except queue.Empty:
            return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            with self._store._lock:
                try:
                    self._store._subscribers.remove(self._q)
                except ValueError:
                    pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class EventStore:
    """Thread-safe ring buffer of system events with SSE subscriber fan-out.

    Ported from orchestrator-service @2bd6d06 (dashboard/SSE concern). In the
    new architecture the queue (Phase 1 PromptInfo) is a separate mechanism;
    this store only records events for the dashboard.
    """

    def __init__(
        self,
        maxlen: int = 1000,
        sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: list[queue.Queue[dict[str, Any] | None]] = []
        self._lock = threading.Lock()
        # Ids are "<boot-epoch>-<seq>": the per-process counter alone would
        # reset to 1 on restart and collide with the UI's seen-id set — every
        # post-restart event at or below the old high-water mark would be
        # silently deduped away (a tab left open across a redeploy freezes).
        # The epoch prefix makes ids unique across restarts instead.
        self._epoch = int(time.time())
        self._counter = itertools.count(1)
        self._sink = sink

    def emit(self, event_type: str, **data: Any) -> None:
        """Append an event and fan-out to all subscribers.

        With a ``sink`` wired (webui plan W1's durable event log), the item
        is handed over after fan-out; a raising sink is logged and swallowed
        so persistence can never fail an emit.
        """
        event = {
            "id": f"{self._epoch}-{next(self._counter)}",
            "type": event_type,
            "ts": time.time(),
            "data": data,
        }
        with self._lock:
            self._events.append(event)
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.put_nowait(event)
            except queue.Full:
                pass
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 - sinks self-swallow; belt+braces
                import logging

                logging.getLogger(__name__).exception("event sink failed")

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the last *limit* events (oldest-first within the window)."""
        if limit <= 0:
            return []
        with self._lock:
            events = list(self._events)
        return events[-limit:] if limit < len(events) else events

    def subscribe(self, keepalive: float = 30.0) -> Subscriber:
        """Register a subscriber that yields events for SSE streaming.

        Returns a :class:`Subscriber` iterator. Existing events are queued
        immediately; new events are delivered as they arrive. On keepalive
        timeout the iterator yields ``None``. Call ``close()`` to deregister.
        """
        q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=500)
        with self._lock:
            for e in list(self._events):
                try:
                    q.put_nowait(e)
                except queue.Full:
                    break
            self._subscribers.append(q)
        return Subscriber(self, q, keepalive)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
