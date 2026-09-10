"""should_dispatch gate tests (webhook_receiver.filters)."""

from __future__ import annotations

import pytest

from webhook_receiver.filters import should_dispatch


def labeled_payload(
    label: str = "orchestration:plan",
    sender: str = "nam20485",
    issue_labels: list[str] | None = None,
) -> dict:
    return {
        "action": "labeled",
        "sender": {"login": sender},
        "label": {"name": label},
        "issue": {
            "number": 1,
            "labels": [{"name": n} for n in (issue_labels or [label])],
        },
        "repository": {"full_name": "owner/repo"},
    }


class TestAccepts:
    def test_orchestration_namespace_label(self) -> None:
        allow, reason = should_dispatch("issues", labeled_payload("orchestration:plan"))
        assert allow is True
        assert reason == "allowed"

    def test_gh_issue_tracking_namespace_label(self) -> None:
        allow, _ = should_dispatch(
            "issues", labeled_payload("gh-issue-tracking:epic")
        )
        assert allow is True

    def test_exact_implementation_labels(self) -> None:
        for label in ("implementation:ready", "implementation:complete"):
            allow, _ = should_dispatch("issues", labeled_payload(label))
            assert allow is True, label


class TestRejects:
    def test_wrong_event_type(self) -> None:
        allow, reason = should_dispatch("push", labeled_payload())
        assert allow is False
        assert "only issues" in reason

    def test_wrong_action(self) -> None:
        payload = labeled_payload()
        payload["action"] = "opened"
        allow, reason = should_dispatch("issues", payload)
        assert allow is False
        assert "only labeled" in reason

    def test_bot_actor_suffix_bot(self) -> None:
        allow, reason = should_dispatch(
            "issues", labeled_payload(sender="ci-bot")
        )
        assert allow is False
        assert "bot actor" in reason

    def test_bot_actor_bracket_bot(self) -> None:
        allow, _ = should_dispatch(
            "issues", labeled_payload(sender="github-actions[bot]")
        )
        assert allow is False

    def test_non_workflow_label(self) -> None:
        allow, reason = should_dispatch("issues", labeled_payload("bug"))
        assert allow is False
        assert "not workflow-relevant" in reason


class TestDirectBodyGate:
    def test_fail_closed_when_allowlist_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DIRECT_BODY_ALLOWED_SENDERS", raising=False)
        allow, reason = should_dispatch(
            "issues", labeled_payload("gh-issue-tracking:direct-body")
        )
        assert allow is False
        assert "disabled" in reason

    def test_untrusted_sender_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DIRECT_BODY_ALLOWED_SENDERS", "trusted-user")
        allow, reason = should_dispatch(
            "issues", labeled_payload("gh-issue-tracking:direct-body")
        )
        assert allow is False
        assert "not permitted" in reason

    def test_trusted_sender_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DIRECT_BODY_ALLOWED_SENDERS", "trusted-user, nam20485")
        allow, _ = should_dispatch(
            "issues", labeled_payload("gh-issue-tracking:direct-body")
        )
        assert allow is True

    def test_direct_body_label_elsewhere_on_issue_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Trigger label is a plain workflow label, but the issue still carries
        # direct-body — dispatch stays fail-closed for untrusted senders.
        monkeypatch.delenv("DIRECT_BODY_ALLOWED_SENDERS", raising=False)
        allow, _ = should_dispatch(
            "issues",
            labeled_payload("orchestration:plan", issue_labels=["gh-issue-tracking:direct-body"]),
        )
        assert allow is False
