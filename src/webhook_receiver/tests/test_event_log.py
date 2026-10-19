"""Tests for the durable event tail (webui plans W1/W2) — event_log, the
EventStore sink seam, and the /runs + /events/history + index endpoints."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from webhook_receiver.app import create_app
from webhook_receiver.config import Settings
from webhook_receiver.event_log import (
    EventLog,
    read_global_tail,
    read_run_events,
)
from webhook_receiver.event_store import EventStore

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"


def make_event(event_type: str, **data: Any) -> dict[str, Any]:
    return {"id": 1, "type": event_type, "ts": 1700000000.0, "data": data}


class TestEventLogRouting:
    def test_run_scoped_event_lands_in_run_file(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path, keep_runs=50)
        log.append(make_event("agent_finished", run_id="a" * 32, ok=True))
        path = tmp_path / ("a" * 32) / "events.jsonl"
        assert json.loads(path.read_text())["type"] == "agent_finished"

    def test_prompt_queued_id_routes_to_run_file(self, tmp_path: Path) -> None:
        # prompt_queued names the envelope id "id", not "run_id".
        log = EventLog(tmp_path, keep_runs=50)
        log.append(make_event("prompt_queued", id="b" * 32, delivery_id="d-1"))
        assert (tmp_path / ("b" * 32) / "events.jsonl").is_file()

    def test_pre_envelope_event_lands_in_global_tail(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path, keep_runs=50)
        log.append(make_event("webhook_filtered", delivery_id="d-2", reason="label"))
        assert json.loads((tmp_path / "events.jsonl").read_text())[
            "type"
        ] == "webhook_filtered"

    def test_traversal_shaped_run_id_falls_back_to_global(
        self, tmp_path: Path
    ) -> None:
        log = EventLog(tmp_path, keep_runs=50)
        for bad in ("../etc", "a/b", "..", "."):
            log.append(make_event("agent_finished", run_id=bad))
        assert (tmp_path / "events.jsonl").read_text().count("\n") == 4
        assert list(tmp_path.iterdir()) == [tmp_path / "events.jsonl"]


class TestEventLogPosture:
    def test_filesystem_failure_never_raises(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "missing" / "denied", keep_runs=50)
        # Root uncreatable (a file blocks the path) — append must swallow.
        blocker = tmp_path / "missing"
        blocker.write_text("not a dir", encoding="utf-8")
        log.append(make_event("webhook_received", delivery_id="d"))
        assert blocker.read_text() == "not a dir"  # nothing clobbered

    def test_global_tail_rotates_at_max_bytes(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path, keep_runs=50, max_bytes=1)
        log.append(make_event("webhook_received", delivery_id="d-1"))
        log.append(make_event("webhook_received", delivery_id="d-2"))
        rotated = tmp_path / "events.jsonl.1"
        current = tmp_path / "events.jsonl"
        assert json.loads(rotated.read_text())["data"]["delivery_id"] == "d-1"
        assert json.loads(current.read_text())["data"]["delivery_id"] == "d-2"

    def test_new_run_dir_prunes_beyond_keep_runs(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path, keep_runs=2)
        for n in range(3):
            log.append(make_event("prompt_queued", id=f"{n:032x}"))
            time.sleep(0.01)  # distinct mtimes for oldest-first pruning
        remaining = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
        assert remaining == [f"{1:032x}", f"{2:032x}"]


class TestEventStoreSink:
    def test_sink_receives_emitted_items(self) -> None:
        seen: list[dict[str, Any]] = []
        store = EventStore(sink=seen.append)
        store.emit("agent_plan", run_id="c" * 32, entries=[])
        assert seen[0]["type"] == "agent_plan"
        assert seen[0]["data"]["run_id"] == "c" * 32
        assert str(seen[0]["id"]).endswith("-1") and "ts" in seen[0]

    def test_raising_sink_does_not_break_emit(self) -> None:
        def boom(_: dict[str, Any]) -> None:
            raise RuntimeError("sink exploded")

        store = EventStore(sink=boom)
        store.emit("webhook_received", delivery_id="d")
        assert store.recent()[0]["type"] == "webhook_received"


class TestRunsEndpoints:
    def make_app(self, tmp_path: Path, events_log: bool = True) -> TestClient:
        settings = Settings(
            host="testserver",
            port=80,
            github_webhook_secret=SECRET,
            max_body_bytes=25 * 1024 * 1024,
            log_level="info",
            acp_enabled=False,  # placeholder consumer: no opencode in tests
            acp_trace_root=str(tmp_path / "runs"),
            events_log_enabled=events_log,
        )
        return TestClient(create_app(settings))

    def seed(self, tmp_path: Path, run_id: str, manifest: dict | None = None) -> None:
        root = tmp_path / "runs"
        directory = root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "events.jsonl").write_text(
            json.dumps(make_event("prompt_queued", id=run_id)) + "\n",
            encoding="utf-8",
        )
        if manifest is not None:
            (directory / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

    def test_runs_index_newest_first_with_manifest(self, tmp_path: Path) -> None:
        old, new = "d" * 32, "e" * 32
        self.seed(tmp_path, old, {"repo": "owner/repo", "ok": False})
        time.sleep(0.01)
        self.seed(tmp_path, new, {"repo": "owner/repo2", "ok": True})
        client = self.make_app(tmp_path)
        body = client.get("/runs").json()
        assert [entry["run_id"] for entry in body] == [new, old]
        assert body[0]["manifest"]["repo"] == "owner/repo2"
        assert body[0]["events_bytes"] > 0

    def test_run_events_returns_history(self, tmp_path: Path) -> None:
        rid = "f" * 32
        self.seed(tmp_path, rid)
        client = self.make_app(tmp_path)
        events = client.get(f"/runs/{rid}/events").json()
        assert events[0]["type"] == "prompt_queued"

    def test_unknown_or_malformed_run_404s(self, tmp_path: Path) -> None:
        client = self.make_app(tmp_path)
        assert client.get("/runs/deadbeef/events").status_code == 404
        # 65 chars: survives routing, fails the 64-cap segment check —
        # this is the request that actually exercises the guard.
        assert client.get("/runs/" + "a" * 65 + "/events").status_code == 404
        assert read_run_events(str(tmp_path), "../etc") is None

    def test_disk_copy_is_redacted(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path, keep_runs=50)
        log.append(
            make_event(
                "agent_message_chunk",
                run_id="9" * 32,
                text="token is ghp_" + "A" * 36 + " ok?",
            )
        )
        stored = (tmp_path / ("9" * 32) / "events.jsonl").read_text()
        assert "ghp_" + "A" * 36 not in stored
        assert "[REDACTED]" in stored

    def test_events_log_disabled_writes_nothing(self, tmp_path: Path) -> None:
        client = self.make_app(tmp_path, events_log=False)
        from webhook_receiver.github import compute_signature

        payload = json.dumps(
            {
                "action": "labeled",
                "sender": {"login": "someone"},
                "label": {"name": "chore"},
                "issue": {"number": 1, "labels": [{"name": "chore"}]},
                "repository": {"full_name": "owner/repo"},
            }
        ).encode()
        client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "d-x",
                "X-Hub-Signature-256": compute_signature(payload, SECRET),
            },
        )
        assert not (tmp_path / "runs").exists()

    def test_live_dispatch_streams_to_run_file(self, tmp_path: Path) -> None:
        # End-to-end through create_app: an accepted delivery's events land
        # in the durable tail (webhook_* global, prompt_queued per-run).
        client = self.make_app(tmp_path)
        from webhook_receiver.github import compute_signature

        payload = json.dumps(
            {
                "action": "labeled",
                "sender": {"login": "nam20485"},
                "label": {"name": "orchestration:plan"},
                "issue": {"number": 1, "labels": [{"name": "orchestration:plan"}]},
                "repository": {"full_name": "owner/repo"},
            }
        ).encode()
        resp = client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "d-live",
                "X-Hub-Signature-256": compute_signature(payload, SECRET),
            },
        )
        assert resp.status_code == 202
        root = tmp_path / "runs"
        global_types = [
            json.loads(line)["type"]
            for line in (root / "events.jsonl").read_text().splitlines()
        ]
        assert global_types[:2] == ["webhook_received", "webhook_accepted"]
        run_ids = [p.name for p in root.iterdir() if p.is_dir()]
        assert len(run_ids) == 1
        run_events = client.get(f"/runs/{run_ids[0]}/events").json()
        # prompt_queued is emitted synchronously at enqueue; the consumer's
        # prompt_consumed may follow, so pin the head, not the whole list.
        assert run_events[0]["type"] == "prompt_queued"


class TestGlobalTailAndIndex:
    def test_read_global_tail_merges_rotated_pair(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "events.jsonl.1").write_text(
            json.dumps(make_event("webhook_received", delivery_id="d-1")) + "\n",
            encoding="utf-8",
        )
        (root / "events.jsonl").write_text(
            json.dumps(make_event("webhook_accepted", delivery_id="d-1")) + "\n",
            encoding="utf-8",
        )
        tail = read_global_tail(str(root))
        assert [item["type"] for item in tail] == [
            "webhook_received",
            "webhook_accepted",
        ]

    def test_history_endpoint_empty_when_never_written(self, tmp_path: Path) -> None:
        client = self.make_app_client(tmp_path)
        assert client.get("/events/history").json() == []

    def test_torn_or_foreign_lines_are_tolerated(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "events.jsonl").write_bytes(
            json.dumps(make_event("webhook_received", delivery_id="d-1")).encode()
            + b"\n"
            + b'{"type": "torn", "data": {"text": "trunc'  # crash mid-write
            + b"\n"
            + b"42\n"  # parses, but not a dict
            + b"\xff\xfe invalid utf8\n"
        )
        tail = read_global_tail(str(root))
        assert [item["type"] for item in tail] == ["webhook_received"]

    def test_history_endpoint_serves_durable_tail(self, tmp_path: Path) -> None:
        root = tmp_path / "runs"
        root.mkdir()
        (root / "events.jsonl").write_text(
            json.dumps(make_event("webhook_filtered", delivery_id="d-9", reason="label"))
            + "\n",
            encoding="utf-8",
        )
        client = self.make_app_client(tmp_path)
        body = client.get("/events/history").json()
        assert body[0]["type"] == "webhook_filtered"
        assert body[0]["data"]["delivery_id"] == "d-9"

    @staticmethod
    def make_app_client(tmp_path: Path) -> TestClient:
        settings = Settings(
            host="testserver",
            port=80,
            github_webhook_secret=SECRET,
            max_body_bytes=25 * 1024 * 1024,
            log_level="info",
            acp_enabled=False,
            acp_trace_root=str(tmp_path / "runs"),
        )
        return TestClient(create_app(settings))

    def test_index_serves_the_static_page(self, tmp_path: Path) -> None:
        client = self.make_app_client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "swarm-orchestration" in resp.text
        # The page must render data as text, never parse it as HTML.
        assert "innerHTML" not in resp.text
