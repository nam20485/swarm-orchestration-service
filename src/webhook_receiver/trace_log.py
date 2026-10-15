"""Per-run harness trace artifacts (``docs/plans/harness-trace-parity.md`` S2).

One directory per dispatched envelope under ``ACP_TRACE_ROOT`` (default
``logs/runs``, relative to the service's working directory and gitignored):

    <root>/<run_id>/harness.log    every harness stderr line, flushed,
                                   credential-redacted, noise-unfiltered
    <root>/<run_id>/manifest.json  identity at start, outcome merged at the end

The journald pane is the readable, filtered view (D2/D3); this directory is the
record that survives a restart. Retention is a run count
(``ACP_TRACE_KEEP_RUNS``, default 50), pruned oldest-first when a run opens.

Trace capture is best-effort by design: any filesystem failure is logged and
the run continues without artifacts, because losing a trace must never fail a
dispatch.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TRACE_ROOT = "logs/runs"
_DEFAULT_KEEP_RUNS = 50

# Envelope ids are uuid4 hex; pruning is restricted to that shape so a
# mis-pointed ACP_TRACE_ROOT can never delete unrelated directories.
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}")

# Credential shapes scrubbed before a line is written anywhere — the ported
# ``_SECRET_PATTERNS`` of the old orchestrator-service runner. ``logs/`` is
# gitignored, but a bare token must not land on disk regardless.
_BARE_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub classic/OAuth tokens
    re.compile(r"github_pat_[A-Za-z0-9]{22,}"),  # GitHub fine-grained PATs
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style API keys
    re.compile(r"[Bb]earer\s+[A-Za-z0-9._-]{20,}"),  # Bearer tokens
)
# key=value assignments keep the key so the line stays diagnosable.
_KV_SECRET_RE = re.compile(
    r"(?i)((?:password|passwd|secret|api[_-]?key|token|auth)\s*[:=]\s*)\S+"
)


def redact(text: str) -> str:
    """Scrub credential values from one trace line.

    Bare token shapes become ``[REDACTED]``; ``key=value`` shapes keep the key
    and replace the value with ``<redacted>``.
    """
    for pattern in _BARE_SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _KV_SECRET_RE.sub(r"\1<redacted>", text)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunTrace:
    """The artifact directory of one run.

    ``open()`` writes the identity manifest, ``write()`` appends raw
    (redacted, unfiltered) harness lines, ``finish()`` merges the outcome, and
    ``close()`` is the idempotent teardown used by the caller's ``finally``.
    """

    def __init__(self, directory: Path, keep_runs: int = _DEFAULT_KEEP_RUNS) -> None:
        self.directory = directory
        self.log_path = directory / "harness.log"
        self.manifest_path = directory / "manifest.json"
        self._keep_runs = max(1, keep_runs)
        self._handle: Any = None
        self._manifest: dict[str, Any] = {}

    def open(self, **fields: Any) -> None:
        self._manifest = {"started_at": _utcnow(), **fields}
        self._handle = self.log_path.open("a", encoding="utf-8")
        self._write_manifest()
        self._prune()

    def write(self, line: str) -> None:
        if self._handle is None:
            return
        self._handle.write(line.rstrip("\n") + "\n")
        self._handle.flush()

    def finish(self, **fields: Any) -> None:
        self._manifest.update(fields)
        self._manifest["ended_at"] = _utcnow()
        self._write_manifest()

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            finally:
                self._handle = None

    def _write_manifest(self) -> None:
        # Atomic replace so a reader never sees a half-written manifest.
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.manifest_path)

    def _prune(self) -> None:
        """Keep the newest ``keep_runs`` run directories, oldest removed."""
        try:
            siblings = [
                entry
                for entry in self.directory.parent.iterdir()
                if entry.is_dir() and _RUN_ID_RE.fullmatch(entry.name)
            ]
        except OSError:
            return
        if len(siblings) <= self._keep_runs:
            return
        siblings.sort(key=lambda p: p.stat().st_mtime)
        for stale in siblings[: len(siblings) - self._keep_runs]:
            if stale == self.directory:
                continue
            try:
                shutil.rmtree(stale)
            except OSError as exc:
                logger.warning("trace prune failed for %s: %s", stale, exc)


def open_run_trace(
    trace_root: str, keep_runs: int, info: Any, workspace: Path
) -> RunTrace | None:
    """Create the trace directory for one envelope, or ``None`` on failure.

    ``info`` is the :class:`~webhook_receiver.prompt_queue.PromptInfo`
    envelope. Never raises: a trace that cannot be created is logged and the
    dispatch proceeds without one.
    """
    root = (
        Path(trace_root).expanduser() if trace_root else Path(_DEFAULT_TRACE_ROOT)
    )
    directory = root / info.id
    try:
        directory.mkdir(parents=True, exist_ok=True)
        trace = RunTrace(directory, keep_runs)
        trace.open(
            run_id=info.id,
            delivery_id=info.delivery_id,
            repo=info.repo,
            event=info.event,
            action=info.action,
            label=info.label,
            workspace=str(workspace),
        )
        return trace
    except OSError as exc:
        logger.warning(
            "harness trace unavailable for run %s (%s): %s", info.id, directory, exc
        )
        return None
