"""Rev2 state-map tests for the orchestration prompt builder.

The label matrix below is the regression checklist for the rev2 rework
(docs/plans/rev2-state-map-design.md §3): every rev2 dispatch label carries
the canonical state map (selection unchanged since Phase 3), every rev1
``orchestration:*`` label gets the deprecated-note fallthrough (and no longer
dispatches at all — pinned in test_filters), and the map itself is guarded
row-by-row for format and contract presence. The retired Phase 3 direction
paragraphs and the old repo's clause-table helpers must never return.
"""

from __future__ import annotations

import json
import re

from webhook_receiver.prompt_builder import (
    _REV2_STATE_MAP,
    build_orchestration_prompt,
)
from webhook_receiver.prompt_queue import PromptInfo

BODY = "Run the deployment drill against staging and report back."

# Labels that dispatch (filters gate) and select the state map. direct-body
# is excluded — it takes the verbatim-body path.
REV2_MAP_LABELS = [
    "gh-issue-tracking:init-success",
    "gh-issue-tracking:epic-implemented",
    "implementation:ready",
    "implementation:complete",
]

# The rev1 vocabulary the old clause table matched on. None of it dispatches
# anymore (gate narrowing) and none of it may improvise a path.
REV1_LABELS = [
    "orchestration:plan-approved",
    "orchestration:epic-complete",
    "orchestration:epic-ready",
    "orchestration:epic-implemented",
    "orchestration:epic-reviewed",
    "orchestration:dispatch",
    "orchestration:plan",
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


class TestMapSelection:
    """Phase 3 selection, unchanged: which labels get the state map."""

    def test_every_rev2_dispatch_label_carries_the_map(self) -> None:
        for label in REV2_MAP_LABELS:
            p = build_orchestration_prompt(make_info(label))
            assert _REV2_STATE_MAP in p, f"{label} prompt lacks the state map"

    def test_gh_issue_tracking_prefix_included(self) -> None:
        # Any label in the prefix namespace dispatches and maps — the
        # vocabulary grows by design without touching selection.
        p = build_orchestration_prompt(make_info("gh-issue-tracking:future-step"))
        assert _REV2_STATE_MAP in p

    def test_map_is_the_direction_exactly_once(self) -> None:
        p = build_orchestration_prompt(make_info("implementation:ready"))
        assert p.count("rev2 tracking pipeline — canonical state map") == 1


class TestMapContracts:
    """§3 contract-presence: the facts a session cannot derive."""

    def test_issue_number_rule_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "ISSUE NUMBER" in p
        assert "NEVER the" in p and "ordinal from a title" in p

    def test_loop_statement_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "the label you apply re-triggers the next run" in p

    def test_one_unit_per_run_rule_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "Advance ONE unit per run" in p

    def test_verify_first_clause_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "confirm the live tracking state (gh) before acting" in p

    def test_completion_markers_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:complete")))
        assert "a story is done when its PR is MERGED and the story issue is closed" in p
        assert "an epic is done when its last story is done and the epic issue is closed" in p

    def test_review_budget_and_park_path_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:complete")))
        assert "3 failed review/fix rounds" in p
        assert "needs-owner" in p

    def test_publish_and_verify_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "never push the default branch" in p
        assert "verify remote reachability" in p

    def test_durable_memory_read_clause_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "Durable state (orient from it first)" in p
        assert "not its first run" in p

    def test_durable_memory_write_clause_present(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "Durable learning (write before you end)" in p
        assert "rules-file edit, proposed in the same PR" in p

    def test_standing_mechanics_status_comments(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "First action: status comment" in p


class TestRowPresence:
    """§3 row presence: each state's canonical next transition, per class."""

    def test_init_success_row_finds_next_unit(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:init-success")))
        assert "the lowest-numbered OPEN issue labeled" in p
        assert "apply `implementation:ready` to that unit" in p

    def test_implementation_ready_row_implements_one_story(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "implement THIS story" in p
        assert "One story per run" in p
        assert "apply `implementation:complete` + `needs-review`" in p

    def test_implementation_complete_row_drives_the_pr_cycle(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:complete")))
        assert "Drive it to merged" in p
        assert "zero unresolved threads" in p
        assert "ALL checks GREEN + MERGEABLE" in p

    def test_epic_implemented_row_is_terminal(self) -> None:
        p = norm(build_orchestration_prompt(make_info("gh-issue-tracking:epic-implemented")))
        assert "Review that epic's merged PRs" in p
        assert "TERMINAL" in p


class TestRowFormatGuard:
    """§3 row-format guard (owner 2026-10-24): every state row carries the
    ``(on the <labelled resource>)`` qualifier and an on-completion
    transition naming the next label — the deprecated-vocabulary row is the
    one exemption (it has no transition by definition)."""

    def _state_rows(self) -> list[str]:
        # State rows are the blank-line-separated blocks starting "- " BEFORE
        # the standing-mechanics section (whose bullets are mechanics, not
        # states). A row's on-completion transition may sit on any of its
        # continuation lines, so the guard reads whole blocks.
        head = _REV2_STATE_MAP.split("Standing mechanics", 1)[0]
        blocks = [b.strip() for b in head.split("\n\n")]
        return [b for b in blocks if b.startswith("- ")]

    def test_every_state_row_has_the_format_markers(self) -> None:
        rows = self._state_rows()
        assert len(rows) == 6  # direct-body, init-success, ready, complete, epic-implemented, deprecated
        for row in rows:
            flat = norm(row)
            # The qualifier family, article-agnostic as the map itself uses
            # it: "(on the Plan issue)", "(on a story)", "(on an epic)",
            # "(on any issue)" for the two wildcard rows.
            assert re.search(r"\(on (the|a|an|any) ", flat), (
                f"row lacks labelled-resource qualifier: {row[:60]}"
            )
            if not row.startswith("- any other dispatch label"):
                # Transition-phrase family: "On completion:" on simple rows;
                # the implementation:complete row's transition is conditional
                # ("After 3 failed rounds ... stop. On merge: close the
                # story, then apply ...").
                assert re.search(r"On (completion|merge):", flat), (
                    f"row lacks on-completion transition: {row[:60]}"
                )

    def test_deprecated_row_names_the_rev1_namespace(self) -> None:
        rows = self._state_rows()
        deprecated = [r for r in rows if r.startswith("- any other dispatch label")]
        assert deprecated
        flat = norm(deprecated[0])
        assert "orchestration:*" in flat
        assert "no matching rev2 clause" in flat


class TestRev1Fallthrough:
    """Every rev1 label → the deprecated note; never the map, never a path."""

    def test_every_rev1_label_gets_the_deprecated_note(self) -> None:
        for label in REV1_LABELS:
            p = norm(build_orchestration_prompt(make_info(label)))
            assert "no matching rev2 clause" in p, f"{label} lacks the note"
            assert _REV2_STATE_MAP not in p, f"{label} unexpectedly carries the map"
            assert label in p  # the triggering label is named

    def test_unmatched_non_rev1_label_gets_the_note_too(self) -> None:
        p = norm(build_orchestration_prompt(make_info("triage:whatever")))
        assert "no matching rev2 clause" in p

    def test_note_never_improvises_a_rev1_path(self) -> None:
        p = norm(build_orchestration_prompt(make_info("orchestration:dispatch")))
        assert "Do not improvise a rev1 path" in p


class TestDirectBody:
    """Unchanged since Phase 3: the body IS the prompt."""

    def test_direct_body_prompt_is_the_body_verbatim(self) -> None:
        info = make_info("gh-issue-tracking:direct-body")
        assert build_orchestration_prompt(info) == BODY

    def test_direct_body_via_issue_labels_not_trigger_label(self) -> None:
        # The old direct-body clause matched on the issue's FULL label set:
        # a differently-triggered dispatch on an issue carrying the label
        # still runs the body verbatim (sender gate stays in filters).
        payload = dict(make_info("implementation:ready").payload)
        payload["issue"] = dict(
            payload["issue"], labels=[{"name": "gh-issue-tracking:direct-body"}]
        )
        info = make_info("implementation:ready", payload=payload)
        assert build_orchestration_prompt(info) == BODY

    def test_direct_body_empty_body_gets_sentinel_direction(self) -> None:
        info = make_info("gh-issue-tracking:direct-body", body="")
        p = norm(build_orchestration_prompt(info))
        assert "empty" in p
        assert "owner/repo" in p
        assert "#12" in p


class TestAbsenceGuards:
    """§3: the retired clause-table helpers and numbered-step scaffolding
    never return to the prompt."""

    def test_retired_helper_names_absent(self) -> None:
        for label in REV2_MAP_LABELS:
            p = build_orchestration_prompt(make_info(label))
            for name in (
                "find_next_unimplemented_epic",
                "extract_epic_from_title",
                "postStatusUpdate",
            ):
                assert name not in p, f"{label} prompt contains {name}"

    def test_no_numbered_step_scaffolding(self) -> None:
        # Clause bodies regrowing as "Step 1 —" procedure lists is the
        # failure mode; the map's rows are transitions, not steps.
        p = build_orchestration_prompt(make_info("gh-issue-tracking:init-success"))
        assert not re.search(r"Step \d", p)

    def test_phase3_direction_paragraphs_retired(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        for phrase in (
            "This is the implementation path for a tracked work item",
            "This is a gh-issue-tracking hierarchy workflow",
            "This is an orchestration lifecycle workflow",
            "no matching workflow was found",
        ):
            assert phrase not in p


class TestPromptContent:
    def test_carries_envelope_context_and_event_data(self) -> None:
        info = make_info("gh-issue-tracking:init-success")
        p = build_orchestration_prompt(info)
        assert "owner/repo" in p
        assert "#12" in p
        assert "gh-issue-tracking:init-success" in p
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
        p = norm(build_orchestration_prompt(make_info("implementation:ready")))
        assert "non-default branch" in p
        assert "pull request" in p
        assert "Never push to the default branch" in p
        assert "reachable on the remote" in p
        assert "leave the issue open" in p

    def test_workflow_definitions_fetched_fresh(self) -> None:
        p = norm(build_orchestration_prompt(make_info("implementation:complete")))
        assert "agent-instructions repo" in p
        assert "entry point, not a fixed sequence" in p

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
        a = build_orchestration_prompt(make_info("implementation:ready"))
        b = build_orchestration_prompt(make_info("implementation:ready"))
        assert a == b

    def test_payload_key_order_does_not_matter(self) -> None:
        info = make_info("implementation:ready")
        reordered = dict(reversed(list(info.payload.items())))
        other = make_info("implementation:ready", payload=reordered)
        assert build_orchestration_prompt(info) == build_orchestration_prompt(other)

    def test_event_data_is_valid_json(self) -> None:
        p = build_orchestration_prompt(make_info("implementation:ready"))
        blob = p.rsplit("```json", 1)[1].split("```", 1)[0]
        assert json.loads(blob)["repository"]["full_name"] == "owner/repo"
