"""Tests for the ops console mount (issues plan I2a): the static console at
/console, its module MIME type, and the best-effort skip when assets are absent."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webhook_receiver.app import create_app
from webhook_receiver.config import Settings

SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"


class TestConsoleMount:
    def test_console_serves_index(self, tmp_path: Path) -> None:
        client = self.make_app_client(tmp_path)
        resp = client.get("/console/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Swarm Ops Console" in resp.text

    def test_console_module_mime(self, tmp_path: Path) -> None:
        # A module script served with a non-JavaScript MIME is refused by the
        # browser, so the type is part of the serving contract, not a detail.
        client = self.make_app_client(tmp_path)
        for asset in ("app.mjs", "data-live.mjs"):
            resp = client.get(f"/console/{asset}")
            assert resp.status_code == 200, asset
            assert resp.headers["content-type"].startswith("text/javascript"), asset

    def test_console_unknown_path_404(self, tmp_path: Path) -> None:
        client = self.make_app_client(tmp_path)
        assert client.get("/console/nope.js").status_code == 404

    def test_console_missing_assets_skips_mount(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Missing console assets must never fail startup or shadow the
        # dashboard endpoints that live alongside the mount.
        monkeypatch.setattr("webhook_receiver.app._console_web_root", lambda: None)
        client = self.make_app_client(tmp_path)
        assert client.get("/console/").status_code == 404
        assert client.get("/").status_code == 200

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
