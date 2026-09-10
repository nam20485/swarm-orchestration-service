"""Tests for the fail-closed ACP permission policy (webhook_receiver.acp_policy)."""

from __future__ import annotations

import pytest
from acp.schema import (
    AllowedOutcome,
    DeniedOutcome,
    PermissionOption,
    ToolCallUpdate,
)

from webhook_receiver.acp_policy import PermissionDecision, decide, respond
from webhook_receiver.config import Settings


def make_settings(**acp: object) -> Settings:
    return Settings(
        host="testserver",
        port=80,
        github_webhook_secret="FAKE-WEBHOOK-SECRET-FOR-TESTING",
        max_body_bytes=25 * 1024 * 1024,
        log_level="info",
        **acp,
    )


def tool_call(kind: str | None = "execute", title: str = "bash", **fields: object):
    return ToolCallUpdate(tool_call_id="tc-1", kind=kind, title=title, **fields)


def options(*kinds: str) -> list[PermissionOption]:
    return [
        PermissionOption(option_id=k, name=k, kind=k)  # type: ignore[arg-type]
        for k in kinds
    ]


class TestDecide:
    def test_read_kind_allowed_always(self) -> None:
        decision = decide(tool_call(kind="read", title="read src/x.py"), make_settings())
        assert decision.action == "allow_always"
        assert "read" in decision.reason

    @pytest.mark.parametrize("kind", ["search", "think", "fetch"])
    def test_all_read_only_kinds_allowed(self, kind: str) -> None:
        assert decide(tool_call(kind=kind), make_settings()).action == "allow_always"

    def test_deny_pattern_rejects_even_read_kind(self) -> None:
        cfg = make_settings(acp_deny_patterns=("\\.env",))
        decision = decide(tool_call(kind="read", title="read .env"), cfg)
        assert decision.action == "reject"
        assert "deny pattern" in decision.reason

    def test_deny_pattern_matches_raw_input(self) -> None:
        cfg = make_settings(acp_deny_patterns=("git\\s+push\\s+--force",))
        call = tool_call(kind="execute", raw_input={"command": "git push --force main"})
        assert decide(call, cfg).action == "reject"

    def test_deny_pattern_is_case_insensitive(self) -> None:
        cfg = make_settings(acp_deny_patterns=("drop\\s+table",))
        call = tool_call(kind="execute", raw_input={"sql": "DROP TABLE users"})
        assert decide(call, cfg).action == "reject"

    def test_invalid_pattern_never_matches(self) -> None:
        cfg = make_settings(acp_deny_patterns=("([unclosed",))
        decision = decide(tool_call(kind="read", title="([unclosed"), cfg)
        assert decision.action == "allow_always"

    def test_unclassified_defaults_to_reject(self) -> None:
        for kind in ("execute", "edit", "delete", "move", "other", None):
            decision = decide(tool_call(kind=kind), make_settings())
            assert decision.action == "reject", kind
            assert "headless default" in decision.reason

    def test_unclassified_allow_once_when_configured(self) -> None:
        cfg = make_settings(acp_default_permission="allow_once")
        decision = decide(tool_call(kind="edit", title="edit src/a.py"), cfg)
        assert decision.action == "allow_once"

    def test_missing_title_and_input_falls_back_to_kind(self) -> None:
        decision = decide(tool_call(kind="execute", title=None), make_settings())
        assert decision.action == "reject"


class TestRespond:
    def test_reject_selects_reject_once_when_offered(self) -> None:
        decision = decide(tool_call(), make_settings())
        response = respond(options("allow_once", "allow_always", "reject_once"), decision)
        assert isinstance(response.outcome, AllowedOutcome)
        assert response.outcome.option_id == "reject_once"

    def test_reject_accepts_reject_always_fallback(self) -> None:
        response = respond(options("reject_always"), PermissionDecision("reject", "r"))
        assert isinstance(response.outcome, AllowedOutcome)
        assert response.outcome.option_id == "reject_always"

    def test_allow_always_prefers_allow_always_then_allow_once(self) -> None:
        decision = PermissionDecision("allow_always", "read")
        assert respond(options("allow_once", "reject_once"), decision).outcome.option_id == "allow_once"
        assert respond(options("allow_always", "allow_once"), decision).outcome.option_id == "allow_always"

    def test_allow_once_prefers_allow_once(self) -> None:
        decision = PermissionDecision("allow_once", "default")
        response = respond(options("allow_always", "allow_once", "reject_once"), decision)
        assert response.outcome.option_id == "allow_once"

    def test_no_matching_option_fails_closed_to_cancelled(self) -> None:
        # Reject decision but agent only offers allows -> dismissed.
        response = respond(options("allow_once", "allow_always"), PermissionDecision("reject", "r"))
        assert isinstance(response.outcome, DeniedOutcome)
        assert response.outcome.outcome == "cancelled"
        # Allow decision but agent offers no allow option -> dismissed too.
        response = respond(options("reject_once"), PermissionDecision("allow_always", "read"))
        assert isinstance(response.outcome, DeniedOutcome)

    def test_empty_options_fail_closed(self) -> None:
        response = respond([], PermissionDecision("allow_always", "read"))
        assert isinstance(response.outcome, DeniedOutcome)
