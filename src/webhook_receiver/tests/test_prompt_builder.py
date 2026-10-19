"""Clause-fidelity matrix tests for the rev2 mechanical clause-table prompt builder.

Regression reference: ``src/webhook_receiver/orchestration_prompt.jinja2.md``
(vendored byte-identical from orchestrator-service @2bd6d06). The Phase 3
open-ended semantics (class-level directions, no next-label chaining) were
reversed by owner direction 2026-10-19 ("mechanical and do the same thing
every time"): these tests assert the OPPOSITE chaining property — each rev2
trigger selects its ported clause, and clauses DO name the next label they
apply, because the label cycle is the state machine. Rev1 ``orchestration:*``
and ``implementation:*`` labels are deprecated and must fall to the
``(default)`` clause.
"""

from __future__ import annotations

import json

from webhook_receiver.prompt_builder import build_orchestration_prompt
from webhook_receiver.prompt_queue import PromptInfo

BODY = "Run the deployment drill against staging and report back."

# The rev2 state-machine alphabet (the gh-issue-tracking-init skill's live
# label vocabulary) and the deprecated rev1 labels that must land in the
# default clause.
REV2_LABELS = [
    "gh-issue-tracking:direct-body",
    "gh-issue-tracking:init-success",
    "gh-issue-tracking:epic-implemented",
]
REV1_DEPRECATED_LABELS = [
    "orchestration:plan-approved",
    "orchestration:epic-complete",
    "orchestration:epic-ready",
    "orchestration:epic-implemented",
    "orchestration:epic-reviewed",
    "orchestration:dispatch",
    "implementation:ready",
    "implementation:complete",
]


def make_info(
    label: str, body: str = BODY, issue_labels: list[str] | None = None, **overrides: object
) -> PromptInfo:
    labels = issue_labels if issue_labels is not None else [label]
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
                "title": "Epic 1: Foundation",
                "body": body,
                "labels": [{"name": n} for n in labels],
            },
            "repository": {"full_name": "owner/repo"},
        },
    }
    fields.update(overrides)
    return PromptInfo(**fields)  # type: ignore[arg-type]


def norm(text: str) -> str:
    """Whitespace-collapsed form so assertions survive prose line wrapping."""
    return " ".join(text.split())


def epic_info() -> PromptInfo:
    """An ``epic-implemented`` delivery on an epic issue (co-label present)."""
    return make_info(
        "gh-issue-tracking:epic-implemented",
        issue_labels=["gh-issue-tracking:epic-implemented", "epic"],
    )


class TestClauseSelection:
    """Deterministic first-match-wins selection over the rev2 clause table."""

    def test_init_success_selects_the_implement_epic_clause(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "Matched clause: `gh-issue-tracking:init-success`" in p
        assert "Scanning for next unimplemented epic" in p
        assert "$next_epic = find_next_unimplemented_epic()" in p
        # Canonical implement-epic contract: $epic is the epic ISSUE NUMBER.
        assert "implement-epic { $epic = $next_epic.number }" in p
        # The state machine's next hop is named (chaining is the design now).
        assert 'apply label "gh-issue-tracking:epic-implemented"' in p

    def test_epic_implemented_with_epic_co_label_selects_completion_clause(self) -> None:
        p = norm(build_orchestration_prompt(epic_info()))
        assert "Matched clause: `gh-issue-tracking:epic-implemented` + `epic`" in p
        assert "review-epic-prs { $epic = $epic_number }" in p
        assert "$workflow_assignment = report-progress, $assignment_inputs = { epic = $epic_number }" in p
        assert "$workflow_assignment = debrief-and-document, $assignment_inputs = { epic = $epic_number }" in p
        # Completion marker + loop + terminal state.
        assert "close this epic issue" in p
        assert "Loop: pick the next unimplemented epic" in p
        assert "All epics are complete! The implementation plan is fully implemented." in p

    def test_epic_implemented_without_epic_co_label_falls_to_default(self) -> None:
        # The old rule: ALL mentioned values in a clause must match.
        p = norm(
            build_orchestration_prompt(make_info("gh-issue-tracking:epic-implemented"))
        )
        assert "Matched clause: `(default)`" in p
        assert "no clause matched" in p

    def test_every_rev1_deprecated_label_falls_to_default(self) -> None:
        for label in REV1_DEPRECATED_LABELS:
            p = norm(build_orchestration_prompt(make_info(label)))
            assert "Matched clause: `(default)`" in p, f"{label} did not fall to default"
            assert "no clause matched" in p

    def test_default_clause_documents_the_rev1_deprecation(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:dispatch")))
        assert "deprecated" in p
        assert "do not improvise a workflow" in p

    def test_unknown_label_falls_to_default(self) -> None:
        p = norm(build_orchestration_prompt(make_info("triage:whatever")))
        assert "Matched clause: `(default)`" in p


class TestDirectBodyClause:
    def test_body_embedded_verbatim_inside_clause_mechanics(self) -> None:
        p = build_orchestration_prompt(make_info("gh-issue-tracking:direct-body"))
        assert f"---BEGIN ISSUE BODY---\n{BODY}\n---END ISSUE BODY---" in p
        n = norm(p)
        assert "Matched clause: `gh-issue-tracking:direct-body`" in n
        assert "Running the issue body directly as a prompt" in n
        # Ported publish & verify + close mechanics from the reference clause.
        assert "git push -u origin <branch>" in n
        assert "gh pr create --head <branch>" in n
        assert "close the issue" in n
        assert "DIRECT_BODY_ALLOWED_SENDERS" in n

    def test_matches_on_issue_label_set_not_just_trigger(self) -> None:
        # The old direct-body clause matched on the issue's FULL label set:
        # a differently-triggered dispatch on an issue carrying the label
        # still runs the body verbatim (sender gate stays in filters).
        info = make_info(
            "gh-issue-tracking:init-success",
            issue_labels=["gh-issue-tracking:direct-body", "gh-issue-tracking:init-success"],
        )
        p = build_orchestration_prompt(info)
        assert f"---BEGIN ISSUE BODY---\n{BODY}\n---END ISSUE BODY---" in p
        # The init-success clause did NOT run despite being the trigger label.
        assert "Scanning for next unimplemented epic" not in p

    def test_empty_body_gets_sentinel_direction(self) -> None:
        info = make_info("gh-issue-tracking:direct-body", body="")
        p = norm(build_orchestration_prompt(info))
        assert "empty" in p
        assert "owner/repo" in p
        assert "#12" in p


class TestMechanicalSemantics:
    """The 2026-10-19 reversal: mechanical clause execution, NOT open-ended
    live-state progression. The Phase 3 dynamic language must be gone."""

    def test_prompt_orders_exact_mechanical_execution(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "selected mechanically" in p
        assert "first match wins" in p
        assert "Execute the clause's steps exactly, in order" in p
        assert "do not skip its status updates" in p

    def test_no_open_ended_progression_language_anywhere(self) -> None:
        infos = [
            make_info("gh-issue-tracking:init-success"),
            epic_info(),
            make_info("orchestration:plan-approved"),
        ]
        for info in infos:
            p = build_orchestration_prompt(info)
            for banned in (
                "live tracking state",
                "Discover from the tracking state",
                "New application",
                "swarm-plan",
                "not a script to replay",
            ):
                assert banned not in p, f"{info.label} prompt still carries {banned!r}"

    def test_label_cycle_is_the_state_machine(self) -> None:
        p = norm(build_orchestration_prompt(epic_info()))
        assert "the label cycle itself is the state machine" in p
        assert "fires the next iteration of this clause" in p

    def test_test_and_debug_modes_ported(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "Test and Debug Modes" in p
        assert "TEST MODE: This is a test." in p
        assert "DEBUG MODE:" in p

    def test_discontinued_memory_graph_machinery_stripped(self) -> None:
        # .agents/rules/tools.md: memory knowledge-graph + sequential-thinking
        # discontinued 2026-09-12 — must not be re-added by the port.
        p = build_orchestration_prompt(make_info("gh-issue-tracking:init-success"))
        for banned in ("search_nodes", "knowledge graph", "sequential_thinking", "add_observations"):
            assert banned not in p


class TestHelperProcedures:
    def test_post_status_update_procedure(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "postStatusUpdate(message)" in p
        assert "gh issue comment <issue_number>" in p
        assert "always create a new comment" in p

    def test_find_next_unimplemented_epic_procedure(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "find_next_unimplemented_epic()" in p
        assert "sub_issues" in p
        assert 'select(.labels[].name == "epic")' in p
        assert "by `number` ascending" in p
        # Rev2 completion marker: closed epics are skipped; the deprecated
        # rev1 implementation:complete label check is not used.
        assert "If the epic is closed, skip it" in p
        assert "the deprecated rev1 `implementation:complete` label check" in p

    def test_title_parsing_helper_retired_for_issue_number_handoffs(self) -> None:
        # The canonical implement-epic / review-epic-prs contract takes the
        # epic ISSUE NUMBER ("Epic issue object or issue number"); a rev2
        # `Epic <N>:` title ordinal is NOT the issue number, so the
        # reference's extract_epic_from_title helper is retired. Found by the
        # pre-merge real-opencode probe, verified against agent-instructions.
        for info in (
            make_info("gh-issue-tracking:init-success"),
            epic_info(),
        ):
            p = build_orchestration_prompt(info)
            assert "extract_epic_from_title" not in p
            assert "$epic_id" not in p
            assert "$implemented_epic" not in p


class TestPromptContent:
    def test_carries_envelope_context_and_event_data(self) -> None:
        info = make_info("gh-issue-tracking:init-success")
        p = build_orchestration_prompt(info)
        assert "owner/repo" in p
        assert "#12" in p
        assert "gh-issue-tracking:init-success" in p
        assert "d-77" in p
        assert '"sender"' in p  # EVENT_DATA payload JSON embedded

    def test_workflow_definitions_fetched_fresh(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "agent-instructions repo" in p
        assert "fetch their current content at runtime" in p

    def test_publish_and_verify_section_present(self) -> None:
        p = norm(build_orchestration_prompt(epic_info()))
        assert "non-default branch" in p
        assert "Never push to the default branch" in p
        assert "reachable on the remote" in p
        assert "leave the issue open" in p

    def test_final_summary_section_present(self) -> None:
        p = norm(build_orchestration_prompt(epic_info()))
        assert "which clause matched" in p

    def test_tolerates_minimal_payload(self) -> None:
        # The smoke (and any non-webhook source) may carry a bare payload.
        info = PromptInfo(
            delivery_id="d-1",
            repo="a/b",
            event="issues",
            action="labeled",
            label="gh-issue-tracking:init-success",
            payload={"smoke": True},
        )
        p = build_orchestration_prompt(info)
        assert "a/b" in p
        assert "(unknown)" in p
        assert '"smoke"' in p


class TestDeterminism:
    def test_same_envelope_same_prompt(self) -> None:
        a = build_orchestration_prompt(make_info("gh-issue-tracking:init-success"))
        b = build_orchestration_prompt(make_info("gh-issue-tracking:init-success"))
        assert a == b

    def test_payload_key_order_does_not_matter(self) -> None:
        info = make_info("gh-issue-tracking:init-success")
        reordered = dict(reversed(list(info.payload.items())))
        other = make_info("gh-issue-tracking:init-success", payload=reordered)
        assert build_orchestration_prompt(info) == build_orchestration_prompt(other)

    def test_event_data_is_valid_json(self) -> None:
        p = build_orchestration_prompt(make_info("gh-issue-tracking:init-success"))
        blob = p.rsplit("```json", 1)[1].split("```", 1)[0]
        assert json.loads(blob)["repository"]["full_name"] == "owner/repo"

    def test_direct_body_with_braces_in_body_is_safe(self) -> None:
        # Clause texts carry literal braces (`{ $epic = ... }`) and bodies may
        # too; the builder must not re-scan substituted content.
        body = 'weird {braces} and __ISSUE_BODY__ and {placeholders}'
        p = build_orchestration_prompt(make_info("gh-issue-tracking:direct-body", body=body))
        assert body in p
