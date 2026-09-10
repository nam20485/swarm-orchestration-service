"""Matrix tests for the Phase 3 orchestration prompt builder.

The label matrix below is the regression checklist from the OLD repo's
431-line match-clause prompt (``orchestration_prompt.jinja2.md`` pinned at
orchestrator-service @2bd6d06): every workflow label that clause table
handled must produce a prompt carrying the equivalent instruction — expressed
as open-ended direction (decide from live tracking state), never as the old
next-label chaining."""

from __future__ import annotations

import json

from webhook_receiver.prompt_builder import build_orchestration_prompt
from webhook_receiver.prompt_queue import PromptInfo

BODY = "Run the deployment drill against staging and report back."

# Every label the old clause table matched on (plus the implementation labels
# the new dispatch gate admits). The no-chaining property is asserted against
# this full set.
OLD_TABLE_LABELS = [
    "orchestration:plan-approved",
    "orchestration:epic-complete",
    "orchestration:epic-ready",
    "orchestration:epic-implemented",
    "orchestration:epic-reviewed",
    "orchestration:dispatch",
    "gh-issue-tracking:init-success",
    "gh-issue-tracking:direct-body",
    "implementation:ready",
    "implementation:complete",
]


def make_info(label: str, body: str = BODY, **overrides: object) -> PromptInfo:
    fields: dict[str, object] = {
        "delivery_id": "d-77",
        "repo": "owner/repo",
        "event": "issues",
        "action": "labeled",
        "label": label,
        "payload": {
            "action": "labeled",
            "sender": {"login": "nam20485"},
            "label": {"name": label},
            "issue": {
                "number": 12,
                "title": "Epic: Phase 1 — Task 1.2 — Data Modeling",
                "body": body,
                "labels": [{"name": label}],
            },
            "repository": {"full_name": "owner/repo"},
        },
    }
    fields.update(overrides)
    return PromptInfo(**fields)  # type: ignore[arg-type]


def norm(text: str) -> str:
    """Whitespace-collapsed form so assertions survive prose line wrapping."""
    return " ".join(text.split())


class TestMatrixOldClauseTable:
    """One test per old clause-table row: the prompt names the equivalent
    open-ended direction for that label."""

    def test_plan_approved_directs_epic_creation(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:plan-approved")))
        assert "epic creation" in p
        assert "next unimplemented" in p

    def test_epic_complete_directs_advancing_the_plan(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-complete")))
        assert "epic creation" in p
        assert "next unimplemented" in p

    def test_epic_ready_directs_epic_implementation(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-ready")))
        assert "epic implementation" in p

    def test_epic_implemented_directs_pr_review(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-implemented")))
        assert "pull-request review" in p

    def test_epic_reviewed_directs_report_and_debrief(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-reviewed")))
        assert "report and debrief" in p

    def test_dispatch_directs_workflow_named_in_body(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:dispatch")))
        assert "issue body names a workflow" in p
        assert "arguments" in p

    def test_init_success_directs_hierarchy_workflow(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "issue-tracking hierarchy" in p
        assert "next unimplemented" in p

    def test_direct_body_prompt_is_the_body_verbatim(self) -> None:
        info = make_info("gh-issue-tracking:direct-body")
        assert build_orchestration_prompt(info) == BODY

    def test_direct_body_via_issue_labels_not_trigger_label(self) -> None:
        # The old direct-body clause matched on the issue's FULL label set:
        # a differently-triggered dispatch on an issue carrying the label
        # still runs the body verbatim (sender gate stays in filters).
        payload = dict(make_info("orchestration:plan").payload)
        payload["issue"] = dict(
            payload["issue"], labels=[{"name": "gh-issue-tracking:direct-body"}]
        )
        info = make_info("orchestration:plan", payload=payload)
        assert build_orchestration_prompt(info) == BODY

    def test_direct_body_empty_body_gets_sentinel_direction(self) -> None:
        info = make_info("gh-issue-tracking:direct-body", body="")
        p = norm(build_orchestration_prompt(info))
        assert "empty" in p
        assert "owner/repo" in p
        assert "#12" in p

    def test_implementation_ready_directs_item_implementation(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "implement the item" in p

    def test_implementation_complete_directs_completion_verification(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:complete")))
        assert "verify its completion" in p

    def test_unmatched_label_reports_no_matching_workflow(self) -> None:
        # The old (default) fallthrough clause: say so on the issue.
        p = norm(build_orchestration_prompt(make_info("triage:whatever")))
        assert "no matching workflow" in p


class TestOpenEndedSemantics:
    """The Phase 3 exit criterion: labels are directed WITHOUT the old
    clause-table's next-label chaining."""

    def test_no_next_label_chaining_anywhere_in_matrix(self) -> None:
        for label in OLD_TABLE_LABELS:
            if label == "gh-issue-tracking:direct-body":
                continue  # verbatim body; chaining does not apply
            p = build_orchestration_prompt(make_info(label))
            for other in OLD_TABLE_LABELS:
                if other != label:
                    assert other not in p, f"{label} prompt chains onto {other}"

    def test_progression_decided_from_live_tracking_state(self) -> None:
        for label in ("orchestration:plan-approved", "gh-issue-tracking:init-success"):
            p = norm(build_orchestration_prompt(make_info(label)))
            assert "live tracking state" in p
            assert "`gh` CLI" in p

    def test_prompt_rejects_hardcoded_label_sequence(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-ready")))
        assert "never from" in p and "label sequence" in p
        assert "state to read" in p


class TestPromptContent:
    def test_carries_envelope_context_and_event_data(self) -> None:
        info = make_info("orchestration:plan-approved")
        p = build_orchestration_prompt(info)
        assert "owner/repo" in p
        assert "#12" in p
        assert "orchestration:plan-approved" in p
        assert "d-77" in p
        assert '"sender"' in p  # EVENT_DATA payload JSON embedded

    def test_names_paths_discovery_new_app_vs_existing_feature(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "New application" in p
        assert "swarm-plan" in p
        assert "gh-issue-tracking-init" in p
        assert "New feature in an existing application" in p
        assert "Epic/Story/Task" in p
        assert "Discover from the tracking state" in p

    def test_publish_and_verify_section_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:dispatch")))
        assert "non-default branch" in p
        assert "pull request" in p
        assert "Never push to the default branch" in p
        assert "reachable on the remote" in p
        assert "leave the issue open" in p

    def test_workflow_definitions_fetched_fresh(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:epic-ready")))
        assert "agent-instructions repo" in p
        assert "entry point, not a fixed sequence" in p

    def test_tolerates_minimal_payload(self) -> None:
        # The smoke (and any non-webhook source) may carry a bare payload.
        info = PromptInfo(
            delivery_id="d-1",
            repo="a/b",
            event="issues",
            action="labeled",
            label="orchestration:plan",
            payload={"smoke": True},
        )
        p = build_orchestration_prompt(info)
        assert "a/b" in p
        assert "(unknown)" in p
        assert '"smoke"' in p


class TestDeterminism:
    def test_same_envelope_same_prompt(self) -> None:
        a = build_orchestration_prompt(make_info("orchestration:plan-approved"))
        b = build_orchestration_prompt(make_info("orchestration:plan-approved"))
        assert a == b

    def test_payload_key_order_does_not_matter(self) -> None:
        info = make_info("orchestration:plan-approved")
        reordered = dict(reversed(list(info.payload.items())))
        other = make_info("orchestration:plan-approved", payload=reordered)
        assert build_orchestration_prompt(info) == build_orchestration_prompt(other)

    def test_event_data_is_valid_json(self) -> None:
        p = build_orchestration_prompt(make_info("orchestration:plan-approved"))
        blob = p.rsplit("```json", 1)[1].split("```", 1)[0]
        assert json.loads(blob)["repository"]["full_name"] == "owner/repo"
