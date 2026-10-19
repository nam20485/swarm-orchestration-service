"""Durable event tail under the trace root (webui plan W1).

Every :class:`~webhook_receiver.event_store.EventStore` emit is appended,
best-effort, as one JSON line so run history survives restarts and ring
churn (``WEBHOOK_EVENTS_MAXLEN`` bounds only the replay window):

    <root>/<run_id>/events.jsonl   events carrying a run id (``run_id`` or
                                   the PromptInfo ``id``) — a sibling of
                                   trace_log's harness.log/manifest.json
    <root>/events.jsonl            everything else (webhook gate decisions
                                   that precede any envelope), rotated to one
                                   previous generation at ``max_bytes``

``WEBHOOK_EVENTS_LOG_ENABLED`` (default on) gates the whole thing
independently of ``ACP_TRACE_ENABLED`` — events are worth keeping even when
stderr capture is off, and the run directory is created by whichever writer
fires first. Run retention rides ``ACP_TRACE_KEEP_RUNS`` (same directory,
same lifecycle). Like trace_log, any filesystem failure is logged and
swallowed: losing an event line must never fail an emit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

from webhook_receiver.trace_log import prune_runs, redact, resolve_trace_root

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BYTES = 5 * 1024 * 1024

# A run-id path segment: same shape class trace_log accepts for run dirs
# (uuid4 hex in production), rejecting traversal and separators outright.
_RUN_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _run_id_of(data: dict[str, Any]) -> str | None:
    """The run an event belongs to, or None for pre-envelope events.

    ``run_id`` is the envelope id carried by queue/sandbox/agent events;
    ``id`` is the same id as named on ``prompt_queued``.
    """
    rid = data.get("run_id") or data.get("id")
    if (
        isinstance(rid, str)
        and rid not in (".", "..")
        and _RUN_SEGMENT_RE.fullmatch(rid)
    ):
        return rid
    return None


def _redact_value(obj: Any) -> Any:
    """Deep-redact string payload values (trace_log parity: a bare token
    must not land on disk, and these files are served back over HTTP)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [_redact_value(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _redact_value(value) for key, value in obj.items()}
    return obj


class EventLog:
    """Appends event items as JSONL under the trace root; never raises."""

    def __init__(
        self,
        root: Path,
        keep_runs: int = 50,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._root = root
        self._keep_runs = keep_runs
        self._max_bytes = max_bytes
        self._global_path = root / "events.jsonl"
        self._global_size: int | None = None  # lazy stat; None = unknown
        self._lock = threading.Lock()

    def append(self, item: dict[str, Any]) -> None:
        """Append one event item (``{id, type, ts, data}``); best-effort."""
        try:
            # The disk copy carries redacted strings; the ring/SSE copy is
            # untouched (the sink receives the item before this rewrite).
            persisted = {**item, "data": _redact_value(item.get("data") or {})}
            line = json.dumps(persisted, separators=(",", ":"), default=str) + "\n"
            rid = _run_id_of(item.get("data") or {})
            with self._lock:
                if rid is None:
                    self._append_global(line)
                else:
                    self._append_run(rid, line)
        except OSError as exc:
            logger.warning("event log unavailable (%s): %s", self._root, exc)

    def _append_global(self, line: str) -> None:
        if self._global_size is None:
            try:
                self._global_size = self._global_path.stat().st_size
            except OSError:
                self._global_size = 0
        if self._global_size >= self._max_bytes:
            # Single-generation rotation: the previous tail moves to .1
            # (overwriting it), so the file pair stays bounded.
            try:
                os.replace(
                    self._global_path, self._root / (self._global_path.name + ".1")
                )
                self._global_size = 0
            except OSError:
                pass  # rotate best-effort; the append still proceeds
        # The root may not exist yet when the first event is a global one
        # (webhook_received precedes any run directory).
        self._root.mkdir(parents=True, exist_ok=True)
        with self._global_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self._global_size += len(line.encode("utf-8"))

    def _append_run(self, rid: str, line: str) -> None:
        directory = self._root / rid
        fresh = not directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
        if fresh:
            # Same lifecycle as harness traces: opening a run prunes the
            # oldest run dirs beyond ACP_TRACE_KEEP_RUNS.
            prune_runs(self._root, self._keep_runs, protect=directory)


def list_runs(trace_root: str) -> list[dict[str, Any]]:
    """Run history index: run dirs that carry an events.jsonl, newest first.

    Each entry merges the run's ``manifest.json`` when present (repo, label,
    outcome) so the index is useful without opening every events file. A
    missing or unreadable root is just an empty history.
    """
    root = resolve_trace_root(trace_root)
    entries: list[dict[str, Any]] = []
    try:
        candidates = [
            entry
            for entry in root.iterdir()
            if entry.is_dir() and (entry / "events.jsonl").is_file()
        ]
    except OSError:
        return []
    for directory in candidates:
        try:
            entry: dict[str, Any] = {
                "run_id": directory.name,
                "events_bytes": (directory / "events.jsonl").stat().st_size,
                "modified_at": directory.stat().st_mtime,
            }
        except OSError:
            # Pruned between the snapshot and the stat — skip, don't 500.
            continue
        manifest = directory / "manifest.json"
        if manifest.is_file():
            try:
                entry["manifest"] = json.loads(
                    manifest.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                pass  # half-written or foreign manifest: index without it
        entries.append(entry)
    entries.sort(key=lambda item: item["modified_at"], reverse=True)
    return entries


def read_global_tail(trace_root: str) -> list[dict[str, Any]]:
    """Durable global tail: the rotated root-level ``events.jsonl`` pair,
    oldest first (previous generation, then current). Empty when the events
    log has never written (or is disabled)."""
    root = resolve_trace_root(trace_root)
    return _read_tail_pair(root / "events.jsonl.1", root / "events.jsonl")


def read_run_events(trace_root: str, run_id: str) -> list[dict[str, Any]] | None:
    """Full per-run event history, oldest first; None when no such run.

    The run id must satisfy the segment shape (traversal rejected).
    """
    if run_id in (".", "..") or not _RUN_SEGMENT_RE.fullmatch(run_id):
        return None
    path = resolve_trace_root(trace_root) / run_id / "events.jsonl"
    if not path.is_file():
        return None  # unknown run — the endpoint 404s on this
    return _read_tail_pair(path)


def _read_tail_pair(*paths: Path) -> list[dict[str, Any]]:
    """Parse JSONL files oldest-path-first; tolerate anything foreign.

    Decoding happens per line inside the tolerance net (UnicodeDecodeError
    is a ValueError), a torn tail line is skipped, and only dict objects
    survive — corrupt content degrades to fewer events, never a 500.
    """
    events: list[dict[str, Any]] = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        for raw_line in raw.splitlines():
            try:
                obj = json.loads(raw_line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events
