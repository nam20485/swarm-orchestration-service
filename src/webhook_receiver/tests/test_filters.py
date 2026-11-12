"""should_dispatch gate tests (webhook_receiver.filters).

Since the rev2 Stage 3 gate narrowing, the trigger-label allowlist is
``gh-issue-tracking:*`` (prefix) + ``implementation:ready|complete`` (exact)
ONLY: the deprecated rev1 ``orchestration:`` prefix was removed (owner
2026-10-24 allow-only decision) — rev1 labels filter like any other
non-workflow label, and new trigger vocabulary dispatches exactly when we
deliberately add it to an allowlist.
"""

from __future__ import annotations

import pytest

from webhook_receiver.filters import _LABEL_PREFIXES, should_dispatch

REV1_LABELS = [
    "orchestration:plan",
    "orchestration:plan-approved",
    "orchestration:epic-complete",
    "orchestration:epic-ready",
    "orchestration:epic-implemented",
    "orchestration:epic-reviewed",
    "orchestration:dispatch",
]


def labeled_payload(
    label: str = "gh-issue-tracking:init-success",
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
    def test_gh_issue_tracking_namespace_label(self) -> None:
        allow, reason = should_dispatch(
            "issues", labeled_payload("gh-issue-tracking:epic")
        )
        assert allow is True
        assert reason == "allowed"

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

    def test_rev1_orchestration_labels_filtered(self) -> None:
        # The allow-only narrowing: every rev1 label is now just a
        # non-workflow label — no path, no default-clause run.
        for label in REV1_LABELS:
            allow, reason = should_dispatch("issues", labeled_payload(label))
            assert allow is False, f"{label} still dispatches"
            assert "not workflow-relevant" in reason

    def test_label_prefix_allowlist_is_rev2_only(self) -> None:
        # Drift guard: adding trigger vocabulary is a deliberate allowlist
        # edit — this pin forces that edit to touch this test too.
        assert "orchestration:" not in _LABEL_PREFIXES
        assert _LABEL_PREFIXES == ("gh-issue-tracking:",)


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
            labeled_payload(
                "implementation:ready",
                issue_labels=["gh-issue-tracking:direct-body"],
            ),
        )
        assert allow is False
