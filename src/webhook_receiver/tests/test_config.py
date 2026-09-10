"""Settings.from_env tests (webhook_receiver.config)."""

from __future__ import annotations

import pytest

from webhook_receiver.config import Settings


class TestFromEnv:
    def test_missing_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OS_WEBHOOK_SECRET", raising=False)
        with pytest.raises(ValueError, match="OS_WEBHOOK_SECRET is required"):
            Settings.from_env()

    def test_blank_secret_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "   ")
        with pytest.raises(ValueError, match="OS_WEBHOOK_SECRET is required"):
            Settings.from_env()

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "FAKE-WEBHOOK-SECRET-FOR-TESTING")
        for name in ("WEBHOOK_HOST", "WEBHOOK_PORT", "WEBHOOK_MAX_BODY_BYTES", "WEBHOOK_LOG_LEVEL"):
            monkeypatch.delenv(name, raising=False)
        cfg = Settings.from_env()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8080
        assert cfg.github_webhook_secret == "FAKE-WEBHOOK-SECRET-FOR-TESTING"
        assert cfg.max_body_bytes == 25 * 1024 * 1024
        assert cfg.log_level == "info"

    def test_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "FAKE-WEBHOOK-SECRET-FOR-TESTING")
        monkeypatch.setenv("WEBHOOK_HOST", "127.0.0.1")
        monkeypatch.setenv("WEBHOOK_PORT", "9000")
        monkeypatch.setenv("WEBHOOK_MAX_BODY_BYTES", "1024")
        monkeypatch.setenv("WEBHOOK_LOG_LEVEL", "DEBUG")
        cfg = Settings.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000
        assert cfg.max_body_bytes == 1024
        assert cfg.log_level == "debug"
