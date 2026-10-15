"""Tests for the per-run harness trace artifacts (webhook_receiver.trace_log)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from webhook_receiver.prompt_queue import PromptInfo
from webhook_receiver.trace_log import RunTrace, open_run_trace, redact

VALID_PAYLOAD = {
    "action": "labeled",
    "repository": {"full_name": "owner/repo"},
}


def make_info(**overrides: object) -> PromptInfo:
    fields: dict[str, object] = {
        "delivery_id": "d-1",
        "repo": "owner/repo",
        "event": "issues",
        "action": "labeled",
        "label": "orchestration:plan",
        "payload": dict(VALID_PAYLOAD),
    }
    fields.update(overrides)
    return PromptInfo(**fields)  # type: ignore[arg-type]


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestRedact:
    """The five credential shapes must never reach a trace file or the log."""

    @pytest.mark.parametrize(
        ("line", "secret"),
        [
            ("gh auth login with ghp_" + "a" * 36, "a" * 36),
            ("using github_pat_" + "b" * 22, "b" * 22),
            # Matches the key=value rule first (api_key=), which is fine: what
            # matters is that the credential value never survives.
            ("OPENAI_API_KEY=sk-" + "c" * 20, "c" * 20),
            ("Authorization: Bearer " + "d" * 24, "d" * 24),
        ],
    )
    def test_bare_token_shapes_are_redacted(self, line: str, secret: str) -> None:
        out = redact(line)
        assert secret not in out
        assert "[REDACTED]" in out or "<redacted>" in out

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("connecting token=supersecret ok", "connecting token=<redacted> ok"),
            ("api_key: abc123", "api_key: <redacted>"),
            ("PASSWORD=hunter2", "PASSWORD=<redacted>"),
            ("secret = 'x'", "secret = <redacted>"),
        ],
    )
    def test_key_value_shapes_keep_the_key(self, line: str, expected: str) -> None:
        assert redact(line) == expected

    def test_ordinary_lines_pass_through(self) -> None:
        line = 'timestamp=2026-09-27T08:06:38.486Z level=INFO message=loop step=0'
        assert redact(line) == line


class TestRunTrace:
    def test_open_write_finish_close(self, tmp_path: Path) -> None:
        directory = tmp_path / "runs" / ("a" * 32)
        directory.mkdir(parents=True)
        trace = RunTrace(directory)

        trace.open(run_id="a" * 32, delivery_id="d-1", repo="owner/repo")
        trace.write("message=loop step=0\n")
        trace.write("message=stream modelID=big-pickle")
        trace.finish(ok=True, stop_reason="end_turn", session_id="sess-1")
        trace.close()

        lines = (directory / "harness.log").read_text(encoding="utf-8").splitlines()
        assert lines == ["message=loop step=0", "message=stream modelID=big-pickle"]

        manifest = read_manifest(directory / "manifest.json")
        assert manifest["run_id"] == "a" * 32
        assert manifest["delivery_id"] == "d-1"
        assert manifest["repo"] == "owner/repo"
        assert manifest["ok"] is True
        assert manifest["stop_reason"] == "end_turn"
        assert manifest["session_id"] == "sess-1"
        assert manifest["started_at"] and manifest["ended_at"]
        assert manifest["started_at"] <= manifest["ended_at"]

    def test_lines_are_flushed_before_finish(self, tmp_path: Path) -> None:
        """A crashed run must still leave the lines it already wrote."""
        directory = tmp_path / ("b" * 32)
        directory.mkdir()
        trace = RunTrace(directory)
        trace.open(run_id="b" * 32)

        trace.write("first")

        assert (directory / "harness.log").read_text(encoding="utf-8") == "first\n"
        trace.close()

    def test_manifest_is_atomic(self, tmp_path: Path) -> None:
        directory = tmp_path / ("c" * 32)
        directory.mkdir()
        trace = RunTrace(directory)
        trace.open(run_id="c" * 32)
        trace.finish(ok=False, error="boom")
        trace.close()

        assert list(directory.glob("*.tmp")) == []
        assert read_manifest(directory / "manifest.json")["error"] == "boom"

    def test_write_before_open_is_a_noop(self, tmp_path: Path) -> None:
        trace = RunTrace(tmp_path / "never-opened")
        trace.write("dropped")  # must not raise
        trace.close()
        assert not (tmp_path / "never-opened" / "harness.log").exists()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        directory = tmp_path / ("d" * 32)
        directory.mkdir()
        trace = RunTrace(directory)
        trace.open(run_id="d" * 32)
        trace.close()
        trace.close()
        trace.write("after close")  # must not raise

    def test_prune_keeps_the_newest_runs(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        # Older runs, then the new one; mtimes forced into a known order.
        names = [f"{i:032x}" for i in range(1, 6)]
        for index, name in enumerate(names):
            (root / name).mkdir()
            os.utime(root / name, (1_600_000_000 + index, 1_600_000_000 + index))

        current = root / ("f" * 32)
        current.mkdir()
        RunTrace(current, keep_runs=3).open(run_id="f" * 32)

        kept = sorted(p.name for p in root.iterdir())
        assert len(kept) == 3
        assert "f" * 32 in kept  # the run being written is never pruned
        assert names[0] not in kept and names[1] not in kept

    def test_prune_ignores_directories_that_are_not_run_ids(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "not-a-run-id").mkdir()
        (root / "keep").mkdir()
        for index in range(4):
            stale = root / f"{index:032x}"
            stale.mkdir()
            os.utime(stale, (1_600_000_000 + index, 1_600_000_000 + index))

        current = root / ("e" * 32)
        current.mkdir()
        RunTrace(current, keep_runs=1).open(run_id="e" * 32)

        remaining = {p.name for p in root.iterdir()}
        assert {"not-a-run-id", "keep", "e" * 32} <= remaining

    def test_keep_runs_below_one_is_clamped(self, tmp_path: Path) -> None:
        directory = tmp_path / ("a" * 32)
        directory.mkdir()
        trace = RunTrace(directory, keep_runs=0)
        trace.open(run_id="a" * 32)  # must not raise or delete the current run
        trace.close()
        assert directory.exists()


class TestOpenRunTrace:
    def test_creates_the_run_directory_with_identity(self, tmp_path: Path) -> None:
        info = make_info()
        root = tmp_path / "runs"

        trace = open_run_trace(str(root), 50, info, Path("/tmp/ws") / info.id)

        assert trace is not None
        manifest = read_manifest(root / info.id / "manifest.json")
        assert manifest["run_id"] == info.id
        assert manifest["delivery_id"] == "d-1"
        assert manifest["repo"] == "owner/repo"
        assert manifest["label"] == "orchestration:plan"
        assert manifest["event"] == "issues"
        assert manifest["action"] == "labeled"
        assert manifest["workspace"] == str(Path("/tmp/ws") / info.id)
        assert "ended_at" not in manifest  # merged at finish()
        trace.close()

    def test_empty_root_defaults_to_logs_runs(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        info = make_info()

        trace = open_run_trace("", 50, info, tmp_path / "ws")

        assert trace is not None
        assert (tmp_path / "logs" / "runs" / info.id / "harness.log").exists()
        trace.close()

    def test_unwritable_root_degrades_to_none(self, tmp_path: Path, caplog) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        info = make_info()

        with caplog.at_level("WARNING", logger="webhook_receiver.trace_log"):
            trace = open_run_trace(str(blocker / "runs"), 50, info, tmp_path)

        assert trace is None
        assert "harness trace unavailable" in caplog.text
