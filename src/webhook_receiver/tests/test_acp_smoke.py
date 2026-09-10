"""Tests for the manual ACP smoke entry point (webhook_receiver.acp_smoke).

Mock-based: the host is monkeypatched, no real opencode."""

from __future__ import annotations

import asyncio

import webhook_receiver.acp_smoke as smoke
from webhook_receiver.acp_host import AcpHostError, AcpRunResult


class TestParseArgs:
    def test_defaults(self) -> None:
        args = smoke.parse_args([])
        assert args.repo == "owner/repo"
        assert args.event == "issues"
        assert args.action == "labeled"
        assert args.label == "orchestration:plan-approved"
        assert args.delivery_id == "smoke-1"
        assert args.prompt is None

    def test_overrides(self) -> None:
        args = smoke.parse_args(
            ["--repo", "a/b", "--label", "implementation:ready", "--prompt", "do x"]
        )
        assert args.repo == "a/b"
        assert args.label == "implementation:ready"
        assert args.prompt == "do x"


class TestBuildEnvelope:
    def test_envelope_carries_built_orchestration_prompt(self) -> None:
        # Phase 3: no --prompt means the BUILT orchestration prompt.
        args = smoke.parse_args(["--delivery-id", "smoke-9"])
        info = smoke.build_envelope(args)
        assert info.delivery_id == "smoke-9"
        assert info.repo == "owner/repo"
        assert info.event == "issues"
        assert info.action == "labeled"
        assert info.label == "orchestration:plan-approved"
        assert info.prompt is not None
        assert "owner/repo" in info.prompt
        assert "orchestration:plan-approved" in info.prompt
        assert "live tracking state" in info.prompt

    def test_envelope_carries_prompt_override(self) -> None:
        args = smoke.parse_args(["--prompt", "custom"])
        assert smoke.build_envelope(args).prompt == "custom"


class TestBuildSettings:
    def test_secret_defaulted_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("OS_WEBHOOK_SECRET", raising=False)
        monkeypatch.delenv("ACP_OPENCODE_BIN", raising=False)
        cfg = smoke.build_settings()
        assert cfg.github_webhook_secret == "smoke-unused"
        assert cfg.acp_opencode_bin == ""

    def test_acp_env_applies(self, monkeypatch) -> None:
        monkeypatch.delenv("OS_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ACP_OPENCODE_BIN", "/bin/oc")
        assert smoke.build_settings().acp_opencode_bin == "/bin/oc"


class TestRun:
    def test_end_turn_exits_zero_and_prints_events(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "FAKE")  # build_settings setdefault is a no-op
        built = []

        class FakeHost:
            def __init__(self, cfg, store) -> None:
                assert isinstance(store, smoke.PrintingStore)
                built.append(cfg)

            async def run(self, info):
                print(f"[event] fake_event: run_id={info.id}", flush=True)
                return AcpRunResult("sess-1", "end_turn", "/tmp/w")

        monkeypatch.setattr(smoke, "AcpHost", FakeHost)

        code = asyncio.run(smoke.run(smoke.parse_args([])))

        assert code == 0
        out = capsys.readouterr().out
        assert "[smoke] envelope id=" in out
        assert "[event] fake_event" in out
        assert "stop_reason=end_turn" in out
        assert built and built[0].acp_enabled is True

    def test_non_end_turn_exits_one(self, monkeypatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "FAKE")

        class FakeHost:
            def __init__(self, cfg, store) -> None:
                pass

            async def run(self, info):
                return AcpRunResult("sess-1", "refusal", "/tmp/w")

        monkeypatch.setattr(smoke, "AcpHost", FakeHost)
        assert asyncio.run(smoke.run(smoke.parse_args([]))) == 1

    def test_main_maps_host_error_to_exit_one(self, monkeypatch) -> None:
        monkeypatch.setenv("OS_WEBHOOK_SECRET", "FAKE")

        class FakeHost:
            def __init__(self, cfg, store) -> None:
                pass

            async def run(self, info):
                raise AcpHostError("opencode binary not found")

        monkeypatch.setattr(smoke, "AcpHost", FakeHost)
        assert smoke.main([]) == 1
