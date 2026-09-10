"""Open-ended orchestration prompt builder (Phase 3).

Replaces the old repo's 431-line match-clause prompt
(``orchestration_prompt.jinja2.md`` pinned at orchestrator-service
@2bd6d06) with natural-language direction built per
docs/plans/orchestrator-service-simplification.md §3.3: the agent decides
workflow progression from LIVE tracking state (issues and labels queried
via ``gh``), never from a hardcoded label→label clause table.

Shape (string composition only — no templating engine, Simplicity First):
one shared workflow template (envelope context, live-state progression,
new-app vs existing-feature path discovery, publish & verify) plus a short
per-label-class direction. The dispatch gate stays in ``filters.py`` — a
``gh-issue-tracking:direct-body`` envelope reaching here was already
sender-authorized, so its ENTIRE issue body becomes the prompt verbatim
(the old clause table's direct-body special case, unchanged).

The listener fills ``info.prompt`` with this builder's output at enqueue
time (docs/plans/promptinfo-design.md §2); the ACP host's prompt seam sends
the envelope's own prompt when filled (``acp_host.build_prompt``).
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
    return (
        "No workflow is named by the triggering label. Post a status comment "
        "on the issue stating that no matching workflow was found, include "
        "the webhook event details for the run log, and end your turn "
        "without taking further action."
    ) + (f" (triggering label: {label})" if label else "")


_ORCHESTRATION_DIRECTION = (
    "This is an orchestration lifecycle workflow: the triggering label names "
    "the workflow step to run from the agent-instructions repo within the "
    "tracked plan's lifecycle — epic creation for the next unimplemented "
    "plan item, epic implementation, pull-request review and merge, "
    "progress report and debrief, or completion of the current stage. When "
    "the issue body names a workflow to dispatch, run that named workflow "
    "with the arguments given in the body. Direct the named workflow, and "
    "let the tracking state you observe decide the concrete next action."
)

_HIERARCHY_DIRECTION = (
    "This is a gh-issue-tracking hierarchy workflow: the triggering label "
    "names a step in building or consuming the repository's issue-tracking "
    "hierarchy (a plan issue with epic/story/task sub-issues). Direct the "
    "corresponding named workflow from the agent-instructions repo: when "
    "the hierarchy was just initialized or extended, enumerate its tracked "
    "issues and continue with the implementation path for the next "
    "unimplemented item — after confirming from live tracking state what "
    "actually exists and what is already done."
)

_IMPLEMENTATION_DIRECTION = (
    "This is the implementation path for a tracked work item: the "
    "triggering label marks the issue ready for implementation, or records "
    "its implementation complete. Direct the implementation workflow from "
    "the agent-instructions repo for this issue: implement the item "
    "(branch, code, tests, pull request) when it is ready, or verify its "
    "completion from live state (merged pull request, green checks) and "
    "record that outcome on the issue."
)


def _direction_for(label: str) -> str:
    label = (label or "").strip().lower()
    if label.startswith("gh-issue-tracking:"):
        return _HIERARCHY_DIRECTION
    if label.startswith("orchestration:"):
        return _ORCHESTRATION_DIRECTION
    if label in _IMPLEMENTATION_LABELS:
        return _IMPLEMENTATION_DIRECTION
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
    """Build the open-ended orchestration prompt for one envelope.

    Label classes (the old clause table's matrix, now open-ended):

    - ``gh-issue-tracking:direct-body`` — the issue body verbatim (sender
      gate already applied upstream in ``filters``); an empty body gets a
      sentinel direction so the agent reports it on the issue.
    - ``gh-issue-tracking:*`` — the named hierarchy workflow.
    - ``orchestration:*`` — the named orchestration lifecycle workflow
      (a body-named dynamic dispatch included).
    - ``implementation:ready`` / ``implementation:complete`` — the
      implementation path for the tracked work item.
    - anything else — report that no matching workflow was found (the old
      ``(default)`` fallthrough).
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
