"""Orchestration prompt builder (Phase 3, reworked rev2 Stage 3).

The old repo's 431-line match-clause prompt (``orchestration_prompt.jinja2.md``
pinned at orchestrator-service @2bd6d06, vendored for reference at
``docs/reference/``) was replaced in Phase 3 by open-ended direction — which
live evidence then showed to be underspecified: the SAME vague prompt on the
same transition produced both the worst run this stack has seen (3.5 h,
nothing published) and the best (6 h 50 m, a story implemented end-to-end).
Variance is what underspecification buys.

The rev2 split (docs/plans/rev2-state-map-design.md, owner 2026-10-24,
"mechanical knowledge, dynamic execution"): DECIDING stays dynamic — the
agent confirms live tracking state via ``gh`` and adapts — while KNOWING the
pipeline's states, transition contracts, and completion markers is written
down once as ``_REV2_STATE_MAP``: every fact a session cannot derive and
nothing it can. Selection is unchanged from Phase 3: the map is injected for
every ``gh-issue-tracking:*`` (prefix) and ``implementation:ready|complete``
(exact) label; ``gh-issue-tracking:direct-body`` keeps its verbatim-body path
(sender gate upstream in ``filters.py``); every ``orchestration:*`` (rev1)
label and anything else gets the deprecated-note fallthrough — and since the
Stage 3 gate narrowing, rev1 labels no longer dispatch at all.

String composition only — no templating engine (Simplicity First). The
listener fills ``info.prompt`` with this builder's output at enqueue time
(docs/plans/completed/promptinfo-design.md §2); the ACP host's prompt seam
sends the envelope's own prompt when filled (``acp_host.build_prompt``).
Output is deterministic for a given envelope: stable prose plus a
key-sorted EVENT_DATA JSON dump.
"""

from __future__ import annotations

import json

from webhook_receiver.prompt_queue import PromptInfo

# Direct-body dispatch (old clause table's confused-deputy path): the
# ENTIRE issue body IS the prompt. Sender authorization remains upstream in
# filters.should_dispatch (fail-closed DIRECT_BODY_ALLOWED_SENDERS gate,
# checked against the issue's full label set — mirrored here).
_DIRECT_BODY_LABEL = "gh-issue-tracking:direct-body"
_IMPLEMENTATION_LABELS = frozenset(
    {"implementation:ready", "implementation:complete"}
)


def _issue(info: PromptInfo) -> dict:
    issue = info.payload.get("issue")
    return issue if isinstance(issue, dict) else {}


def _issue_labels(info: PromptInfo) -> list[str]:
    """Sorted lowercase label names currently on the issue."""
    names = {
        str(lbl.get("name") or "").strip().lower()
        for lbl in _issue(info).get("labels") or []
        if isinstance(lbl, dict)
    }
    return sorted(n for n in names if n)


def _is_direct_body(info: PromptInfo) -> bool:
    # Same match the old clause used and the filter gates on: the issue's
    # full label set, not just the triggering label.
    return (
        info.label.strip().lower() == _DIRECT_BODY_LABEL
        or _DIRECT_BODY_LABEL in _issue_labels(info)
    )


def _unmatched_direction(label: str) -> str:
    # Deprecated rev1 vocabulary (all orchestration:* — removed from the
    # dispatch gate in this same change, so reaching here means direct/smoke
    # use) and unrecognized labels: never improvise a rev1 path.
    return (
        "No rev2 clause matches the triggering label — deprecated rev1 "
        "vocabulary (orchestration:* labels) or an unrecognized label. Do "
        "not improvise a rev1 path: post a short status comment on the "
        "issue stating that no matching rev2 clause was found, then end "
        "your turn without taking further action."
    ) + (f" (triggering label: {label})" if label else "")


# The rev2 state map (docs/plans/rev2-state-map-design.md §2 — this text IS
# the shipped artifact; keep it byte-faithful to the design doc). One
# constant so the future D re-home into the /orchestrate-swarm skill is a
# move, not a rewrite. Row format (owner 2026-10-24): "<label> (on the
# <labelled resource>) — context and instructions → on completion, what to
# do and which label advances the cycle."
_REV2_STATE_MAP = """\
rev2 tracking pipeline — canonical state map

You were dispatched by a label transition on an issue. The label is pipeline
STATE, not a script: confirm the live tracking state (gh) before acting, then
advance the pipeline along the canonical transition below. Deviate when live
state demands it, and say why in your status comment. Advance ONE unit per run,
then end your turn — the label you apply re-triggers the next run.

States and their canonical next transitions. Row format (owner 2026-10-24):
`<label> (on the <labelled resource>) — context and instructions → on
completion, what to do and which label advances the cycle.`

- gh-issue-tracking:direct-body (on any issue) — kickoff: the issue body IS
  the assignment. Execute it verbatim inside the standing mechanics (below).
  On completion: the body's own stated outcome — e.g. a body running
  `/gh-issue-tracking-init` ends with `gh-issue-tracking:init-success`
  applied to the Plan issue.

- gh-issue-tracking:init-success (on the Plan issue) — the hierarchy
  exists; implementation begins. Find the next unimplemented unit: the
  lowest-numbered OPEN issue labeled `story` (or `epic` if the plan tracks
  epics directly), not closed and not already complete. On completion:
  apply `implementation:ready` to that unit.

- implementation:ready (on a story) — implement THIS story: read it and
  its epic, branch, code, tests, validation, PR (publish & verify below).
  One story per run. On completion: apply `implementation:complete` +
  `needs-review` to the story.

- implementation:complete (on a story) — the story's PR exists and claims
  done. Drive it to merged: dispatch 2–3 subagent reviewers to review the
  PR and post comments for found issues, then run /resolve-pr-comments
  until unresolved threads = 0 and /fix-failing-workflows until checks are
  green; re-read thread state on the head SHA before merging. Merge gate:
  ALL checks GREEN + MERGEABLE + zero unresolved threads — otherwise no
  merge; escalate only when there is no path to resolution. After 3 failed
  review/fix rounds: park the PR with `needs-owner` and stop. On merge:
  close the story, then apply `implementation:ready` to the epic's next
  open story — or, if it was the last, apply
  `gh-issue-tracking:epic-implemented` to the epic.

- gh-issue-tracking:epic-implemented (on an epic) — one epic done. Review
  that epic's merged PRs (review-epic-prs), post a progress report on the
  Plan issue, close the epic. On completion: apply `implementation:ready`
  to the next unimplemented unit; none left → the plan is fully
  implemented: post the final summary and close the Plan issue. TERMINAL.

- any other dispatch label (on any issue) — deprecated rev1 vocabulary
  (all `orchestration:*`; after Stage 3's gate narrowing these should never
  dispatch at all). Do not improvise a rev1 path: post a short "no matching
  rev2 clause" status comment and end the turn.

Standing mechanics (every state):
- First action: status comment on the triggering issue stating what you are
  doing; last action: the outcome summary.
- Workflow contracts (nam20485/agent-instructions): implement-epic and
  review-epic-prs take $epic = the epic's ISSUE NUMBER — NEVER the "Epic N:"
  ordinal from a title, which is not the issue number. Named single
  workflows take $workflow_assignment + $assignment_inputs.
- Completion markers: a story is done when its PR is MERGED and the story
  issue is closed; an epic is done when its last story is done and the epic
  issue is closed (issues.closed is ignored by the gate). Never apply rev1
  labels such as implementation:complete-epic or orchestration:*.
- Labels are the pipeline's clock: apply ONLY the designed next-transition
  label, with the account you hold — each label application re-enters the
  dispatch gate.
- Publish & verify: non-default branch + PR, never push the default branch;
  verify remote reachability before declaring done; close the triggering
  issue only on success.
- The issue body overrides this map when it names a workflow with explicit
  arguments.
- Durable state (orient from it first): the issues, labels and PRs; the
  clone's `.agents/memory.md` (progress and gotchas from previous runs);
  the clone's `.agents/rules/` (the how: PR/merge, commit, testing
  policy). You are this run's only orchestrator, but not its first run.
  Orient fast; when the canonical next step is clear, act rather than
  re-deriving the pipeline.
- Durable learning (write before you end): append a dated entry to
  `.agents/memory.md` — what this run completed, anything that went wrong
  and the fix that finally worked. It rides the run's PR; for runs that
  open no PR, commit it directly to the default branch (`.agents/`
  bookkeeping only — never work product). A lesson that should govern
  future runs is a rules-file edit, proposed in the same PR.
"""


def _direction_for(label: str) -> str:
    label = (label or "").strip().lower()
    if label.startswith("gh-issue-tracking:") or label in _IMPLEMENTATION_LABELS:
        return _REV2_STATE_MAP
    return _unmatched_direction(label)


_WORKFLOW_TEMPLATE = """You are the orchestration agent for the GitHub repository {repo}.

An accepted GitHub webhook delivery triggered this run:
- issue: #{number} {title}
- triggering label: {label}
- labels currently on the issue: {issue_labels}
- delivery id: {delivery_id}

Full webhook payload (EVENT_DATA, JSON):

```json
{event_data}
```

## Workflow

{direction}

Workflow definitions live in the external agent-instructions repo — fetch
their current content at runtime rather than assuming; the label marks the
entry point, not a fixed sequence.

## Deciding progression — from live tracking state

Decide what to do next from the repository's live tracking state, never
from a hardcoded label sequence: before acting, use the `gh` CLI to inspect
the state that matters (the issue's current labels, its sub-issues, sibling
issues and their labels, open pull requests), choose the next action from
what you actually find, and re-check after each action. Labels on issues
are state to read, not a script to replay: record outcomes by publishing
state (comments, labels, pull requests), and let later runs — deciding
again from tracking state — carry the workflow forward.

## Choosing the path — new app vs existing feature

Discover from the tracking state which situation applies before planning
work; do not assume it from this prompt:

- New application (no application plan or tracking hierarchy exists yet):
  plan the app (the swarm-plan wizard — autonomous variant for unattended
  runs), initialize its issue-tracking hierarchy (gh-issue-tracking-init),
  then run the swarm to implement it.
- New feature in an existing application (a tracking hierarchy already
  exists): plan against the existing tracking and file the work as new
  Epic/Story/Task issues under the existing board and label taxonomy, then
  run the swarm.

## Publish & verify

Publish results the way the in-repo workflows already specify: work on a
non-default branch, open or update a pull request, and post the outcome to
the issue (a status comment, plus any labels your workflow conventions use
to record state). Never push to the default branch. Before declaring the
work finished, verify it is reachable on the remote (branch pushed, pull
request open). If the work fails or cannot be published, leave the issue
open and post a comment describing the failure and the next step.

Finish your turn with a short summary of what you found, decided, did, and
published."""


def _workflow_prompt(info: PromptInfo) -> str:
    issue = _issue(info)
    return _WORKFLOW_TEMPLATE.format(
        repo=info.repo,
        number=issue.get("number", "(unknown)"),
        title=issue.get("title") or "(unknown)",
        label=info.label,
        issue_labels=", ".join(_issue_labels(info)) or "(none)",
        delivery_id=info.delivery_id,
        event_data=json.dumps(info.payload, sort_keys=True, indent=2),
        direction=_direction_for(info.label),
    )


_EMPTY_BODY_SENTINEL = (
    "Direct-body dispatch accepted for {repo}: the labeled issue #{number} "
    "carries an empty body, so there is no prompt content to run. Post a "
    "status comment on the issue explaining that the direct-body dispatch "
    "was empty, then end your turn."
)


def build_orchestration_prompt(info: PromptInfo) -> str:
    """Build the orchestration prompt for one envelope.

    Label classes (selection unchanged since Phase 3):

    - ``gh-issue-tracking:direct-body`` — the issue body verbatim (sender
      gate already applied upstream in ``filters``); an empty body gets a
      sentinel direction so the agent reports it on the issue.
    - ``gh-issue-tracking:*`` and ``implementation:ready|complete`` — the
      rev2 state map (``_REV2_STATE_MAP``).
    - anything else, including every ``orchestration:*`` rev1 label — the
      deprecated-note fallthrough (rev1 labels no longer dispatch at all
      after the Stage 3 gate narrowing).
    """
    if _is_direct_body(info):
        body = _issue(info).get("body")
        if isinstance(body, str) and body.strip():
            return body
        issue = _issue(info)
        return _EMPTY_BODY_SENTINEL.format(
            repo=info.repo, number=issue.get("number", "(unknown)")
        )
    return _workflow_prompt(info)
