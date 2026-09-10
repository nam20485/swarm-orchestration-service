"""PromptInfo envelope and the in-process async prompt queue (Phase 1/2).

The listener enqueues one :class:`PromptInfo` per accepted webhook delivery;
a single consumer task drains it. With a host attached (Phase 2 ACP host),
the consumer drives one cold ACP session per envelope and merges the run
outcome into ``prompt_consumed``; without one it only marks envelopes
consumed (the Phase 1 placeholder, still the default for a queue constructed
without a host). Lifecycle events land in the EventStore either way.
Substrate and durability posture per docs/plans/promptinfo-design.md §3/§5:
unbounded ``asyncio.Queue``, bounded delivery-id dedup (last 1024), no
persistence — GitHub redelivery is the recovery path for anything lost to a
restart.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from webhook_receiver.event_store import EventStore

if TYPE_CHECKING:
    from webhook_receiver.acp_host import AcpHost

logger = logging.getLogger(__name__)

# Bounded dedup registry size (docs/plans/promptinfo-design.md §3): comfortably
# exceeds GitHub's redelivery window.
_DEDUP_CAPACITY = 1024


class PromptInfo(BaseModel):
    """Typed envelope for one accepted delivery (design doc §2).

    Frozen after construction — the consumer derives its consumed state via
    ``model_copy``. Every field maps 1:1 onto a future Redis-stream/sqlite
    entry, so a substrate swap never changes the envelope shape or the
    listener.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source: Literal["github_webhook"] = "github_webhook"
    delivery_id: str
    repo: str
    event: str
    action: str
    label: str
    payload: dict[str, Any]
    # Phase 1 leaves the prompt empty (pointer semantics); Phase 3's
    # orchestration-prompt build fills it.
    prompt: str | None = None
    # Reserved for a priority-capable substrate; FIFO ordering ignores it.
    priority: int = 0
    status: Literal["queued", "consumed"] = "queued"
    enqueued_at: float = Field(default_factory=time.monotonic)
    consumed_at: float | None = None


class PromptQueue:
    """In-process FIFO of :class:`PromptInfo` with delivery-id dedup.

    GitHub redelivers (at-least-once), so ``enqueue`` drops envelopes whose
    ``delivery_id`` was already accepted within the last ``dedup_capacity``
    deliveries and returns ``False`` for the caller to record
    ``webhook_duplicate``.
    """

    def __init__(
        self,
        store: EventStore,
        dedup_capacity: int = _DEDUP_CAPACITY,
        host: AcpHost | None = None,
    ) -> None:
        self._queue: asyncio.Queue[PromptInfo] = asyncio.Queue()
        self._store = store
        self._seen_order: deque[str] = deque(maxlen=dedup_capacity)
        self._seen: set[str] = set()
        self._host = host

    def enqueue(self, info: PromptInfo) -> bool:
        """Queue *info* unless its ``delivery_id`` was already seen.

        Returns ``False`` (no-op) for a duplicate; the caller emits
        ``webhook_duplicate`` and still acks GitHub with 202.
        """
        delivery_id = info.delivery_id
        if delivery_id in self._seen:
            return False
        if self._seen_order.maxlen and len(self._seen_order) == self._seen_order.maxlen:
            # deque(maxlen=...) would evict silently; keep the set in sync.
            self._seen.discard(self._seen_order[0])
        self._seen_order.append(delivery_id)
        self._seen.add(delivery_id)
        self._queue.put_nowait(info)
        return True

    async def consume(self) -> None:
        """Drain the queue FIFO, executing each envelope.

        With an ACP host attached (Phase 2): one cold ACP session per
        envelope (plan §5 Decision 4); the host streams its own agent_* events
        into the store and returns the run outcome, merged into
        ``prompt_consumed``. Without a host, this is the Phase 1 placeholder:
        mark consumed and record the event. On exception the envelope is
        logged, recorded as ``prompt_consumed {ok: false}`` and dropped — no
        retry (durability posture: none; GitHub redelivery recovers).
        Cancellation (lifespan shutdown) propagates after the host's own
        kill-on-exit cleanup; the dropped envelope recovers via redelivery.
        """
        while True:
            info = await self._queue.get()
            try:
                result: Any = None
                if self._host is not None:
                    result = await self._host.run(info)
                consumed = info.model_copy(
                    update={"status": "consumed", "consumed_at": time.monotonic()}
                )
                logger.info(
                    "Prompt consumed id=%s delivery_id=%s event=%s action=%s%s%s",
                    consumed.id,
                    consumed.delivery_id,
                    consumed.event,
                    consumed.action,
                    f" session_id={result.session_id}" if result else "",
                    f" stop_reason={result.stop_reason}" if result else "",
                )
                data: dict[str, Any] = {
                    "id": consumed.id,
                    "delivery_id": consumed.delivery_id,
                    "repo": consumed.repo,
                    "event": consumed.event,
                    "action": consumed.action,
                    "label": consumed.label,
                    "ok": True,
                }
                if result is not None:
                    data["session_id"] = result.session_id
                    data["stop_reason"] = result.stop_reason
                self._store.emit("prompt_consumed", **data)
            except Exception as exc:
                logger.exception(
                    "Prompt consumption failed id=%s delivery_id=%s",
                    info.id,
                    info.delivery_id,
                )
                self._store.emit(
                    "prompt_consumed",
                    id=info.id,
                    delivery_id=info.delivery_id,
                    ok=False,
                    error=str(exc) or type(exc).__name__,
                )
            finally:
                self._queue.task_done()
