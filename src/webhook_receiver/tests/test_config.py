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
        for name in (
            "WEBHOOK_HOST",
            "WEBHOOK_PORT",
            "WEBHOOK_MAX_BODY_BYTES",
            "WEBHOOK_LOG_LEVEL",
            "ACP_ENABLED",
            "ACP_OPENCODE_BIN",
            "ACP_WORKSPACE_ROOT",
            "ACP_STEP_TIMEOUT",
            "ACP_PROMPT_TIMEOUT",
            "ACP_DEFAULT_PERMISSION",
            "ACP_DENY_PATTERNS",
            "ACP_DENIED_TOOLS",
        ):
            monkeypatch.delenv(name, raising=False)
        cfg = Settings.from_env()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8080
        assert cfg.github_webhook_secret == "FAKE-WEBHOOK-SECRET-FOR-TESTING"
        assert cfg.max_body_bytes == 25 * 1024 * 1024
        assert cfg.log_level == "info"
        # ACP host defaults (Phase 2): enabled, PATH-resolved opencode,
        # tmpdir workspaces, headless-safe permissions.
        assert cfg.acp_enabled is True
        assert cfg.acp_opencode_bin == ""
        assert cfg.acp_workspace_root == ""
        assert cfg.acp_step_timeout == 30.0
        assert cfg.acp_prompt_timeout == 600.0
        assert cfg.acp_default_permission == "reject"
        assert cfg.acp_deny_patterns == ()
        assert cfg.acp_denied_tools == ()

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


class TestAcpFromEnv:
    """ACP-host settings surface (Phase 2)."""

    SECRET = "FAKE-WEBHOOK-SECRET-FOR-TESTING"

    def test_acp_enabled_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", self.SECRET)
        for value, expected in (("false", False), ("0", False), ("yes", True)):
            monkeypatch.setenv("ACP_ENABLED", value)
            assert Settings.from_env().acp_enabled is expected

    def test_acp_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setenv("ACP_OPENCODE_BIN", "/usr/local/bin/opencode")
        monkeypatch.setenv("ACP_WORKSPACE_ROOT", "/tmp/ws")
        monkeypatch.setenv("ACP_STEP_TIMEOUT", "5.5")
        monkeypatch.setenv("ACP_PROMPT_TIMEOUT", "120")
        monkeypatch.setenv("ACP_DEFAULT_PERMISSION", "allow_once")
        monkeypatch.setenv("ACP_DENY_PATTERNS", "rm\\s+-rf, git\\s+push\\s+--force")
        monkeypatch.setenv("ACP_DENIED_TOOLS", "bash, write")
        cfg = Settings.from_env()
        assert cfg.acp_opencode_bin == "/usr/local/bin/opencode"
        assert cfg.acp_workspace_root == "/tmp/ws"
        assert cfg.acp_step_timeout == 5.5
        assert cfg.acp_prompt_timeout == 120.0
        assert cfg.acp_default_permission == "allow_once"
        assert cfg.acp_deny_patterns == ("rm\\s+-rf", "git\\s+push\\s+--force")
        assert cfg.acp_denied_tools == ("bash", "write")

    def test_invalid_default_permission_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setenv("ACP_DEFAULT_PERMISSION", "allow_always")
        with pytest.raises(ValueError, match="ACP_DEFAULT_PERMISSION must be one of"):
            Settings.from_env()

    def test_invalid_deny_pattern_raises_at_boot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", self.SECRET)
        monkeypatch.setenv("ACP_DENY_PATTERNS", "([unclosed")
        with pytest.raises(ValueError, match="not a valid regex"):
            Settings.from_env()

    def test_dataclass_defaults_keep_direct_construction_working(self) -> None:
        # Phase 1 call sites construct Settings with the listener fields only;
        # the ACP knobs must default so those keep working unchanged.
        cfg = Settings(
            host="h",
            port=1,
            github_webhook_secret="s",
            max_body_bytes=10,
            log_level="info",
        )
        assert cfg.acp_enabled is True
        assert cfg.acp_default_permission == "reject"
