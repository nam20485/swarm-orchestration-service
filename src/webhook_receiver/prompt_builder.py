"""Mechanical rev2 clause-table orchestration prompt builder.

Owner direction 2026-10-19 reversed the Phase 3 open-ended design ("I don't
want it to be dynamic - I want it to be mechanical and do the same thing
every time"): this module restores the match-clause state machine of the old
orchestrator-service prompt, keyed to the rev2 ``gh-issue-tracking:*`` label
vocabulary — the live label set the gh-issue-tracking-init skill stamps on
every target repo (``direct-body``, ``init-success``, ``epic-implemented``).
The rev1 ``orchestration:*`` and ``implementation:*`` namespaces are
deprecated (docs/plans/skill-plan.md taxonomy) and fall to the ``(default)``
clause.

Regression reference: ``orchestration_prompt.jinja2.md`` vendored beside this
module (byte-identical to orchestrator-service @2bd6d06's 431-line match-clause
prompt). Clause BODIES are ported from it near-verbatim; clause SELECTION —
which the old prompt delegated to the LLM ("first match wins" scanning over
EVENT_DATA) — is deterministic Python here: exact trigger-label match plus
co-label requirements, first match wins.

The state machine (each clause publishes the next state; the applied label's
webhook re-triggers dispatch — the label cycle itself is the progression
mechanism):

    gh-issue-tracking:direct-body       run the dispatch issue body verbatim
                                        (kickoff; e.g. /gh-issue-tracking-init,
                                        whose skill applies init-success to the
                                        Plan issue on completion)
    gh-issue-tracking:init-success      scan Plan sub-issues → first
                                        unimplemented epic → implement-epic →
                                        apply epic-implemented to that epic
    gh-issue-tracking:epic-implemented  (+ ``epic`` co-label) review-epic-prs →
                                        report-progress (+ action items) →
                                        debrief-and-document → close epic →
                                        LOOP: next unimplemented epic →
                                        implement-epic → apply epic-implemented;
                                        none left → 🏁 fully implemented, close
                                        the Plan issue
    (default)                           "no clause matched" status comment +
                                        EVENT_DATA dump (where every deprecated
                                        rev1 label intentionally lands)

Adaptations from the reference file (each documented at its clause): the
memory-graph startup/finale and sequential-thinking are stripped (discontinued
in this repo, ``.agents/rules/tools.md``); epic completion is marked by closing
the epic issue rather than the deprecated rev1 ``implementation:complete``
label (which would re-enter the dispatch gate and burn a default-clause run);
``extract_epic_from_title`` parses the skill's ``Epic <N>: <Name>``
numbered-title convention; the Phase 3 new-app-vs-existing-feature discovery
section is dropped (the direct-body kickoff issue carries the explicit
instructions).

Shape (string composition only — no templating engine, Simplicity First):
one scaffold (envelope context, key-sorted EVENT_DATA JSON, mechanical-
execution preamble, matched clause, test/debug modes, helper-function
procedures, publish & verify, final summary). The dispatch gate stays in
``filters.py``; the direct-body sender allowlist is enforced there before a
body can ever run verbatim.

The listener fills ``info.prompt`` with this builder's output at enqueue
time (docs/plans/completed/promptinfo-design.md §2); the ACP host's prompt seam
sends the envelope's own prompt when filled (``acp_host.build_prompt``).
Output is deterministic for a given envelope: stable prose plus a key-sorted
EVENT_DATA JSON dump.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from webhook_receiver.prompt_queue import PromptInfo

# Direct-body dispatch (the old clause table's confused-deputy path): the
# ENTIRE issue body IS the prompt. Sender authorization remains upstream in
# filters.should_dispatch (fail-closed DIRECT_BODY_ALLOWED_SENDERS gate,
# checked against the issue's full label set — mirrored here).
_DIRECT_BODY_LABEL = "gh-issue-tracking:direct-body"

# Sentinel replaced (via str.replace, never str.format — clause texts carry
# literal braces from the `/orchestrate-dynamic-workflow { $arg = ... }`
# syntax) with the dispatch issue's verbatim body.
_BODY_TOKEN = "__ISSUE_BODY__"


# ── Clause bodies — ported from orchestration_prompt.jinja2.md ────────────

_INIT_SUCCESS_CLAUSE = """\
## Matched clause: `gh-issue-tracking:init-success`

## /gh-issue-tracking-init skill completed successfully — begin epic implementation.
## Label-driven: matches on `gh-issue-tracking:init-success` regardless of title format.
## The triggering issue is the main plan issue; the epics already exist as its
## GitHub sub-issues (created by /gh-issue-tracking-init), so no create-epic step
## is needed — just find the next unimplemented one and implement it.

- postStatusUpdate("🤖 Orchestrator matched `gh-issue-tracking:init-success` clause. Scanning for next unimplemented epic...")
- $next_epic = find_next_unimplemented_epic()
- if $next_epic is null:
  - postStatusUpdate("✅ All epics are already complete. The implementation plan is fully implemented.")
  - skip to ##Final.
- postStatusUpdate("🤖 Next unimplemented epic found: #" + $next_epic.number + " — " + $next_epic.title + ". Starting `implement-epic`...")
- $epic_id = extract_epic_from_title($next_epic.title)
- if $epic_id is null:
  - postStatusUpdate("❌ Could not parse epic identifier from issue title (#" + $next_epic.number + "). Cannot proceed with implementation.")
  - comment on the issue with an error explaining the title could not be parsed, then skip to ##Final.
- /orchestrate-dynamic-workflow
    $workflow_name = implement-epic { $epic = $epic_id }
- if implement-epic succeeds:
  - postStatusUpdate("✅ `implement-epic` completed for epic #" + $next_epic.number + " (" + $epic_id + "). Applying `gh-issue-tracking:epic-implemented` label.")
  - apply label "gh-issue-tracking:epic-implemented" to that epic issue (issue number $next_epic.number).
    ## NEXT STAGE: applying the label fires the next webhook; the
    ## `gh-issue-tracking:epic-implemented` clause runs review-epic-prs →
    ## report-progress → debrief-and-document → completion, then loops back
    ## to pick the next unimplemented epic. (The reference file documents
    ## this follow-on as deferred; it is implemented in this builder.)
- else → postStatusUpdate("❌ `implement-epic` failed for epic #" + $next_epic.number + " (" + $epic_id + "). See workflow run logs."), skip to ##Final."""

_EPIC_IMPLEMENTED_CLAUSE = """\
## Matched clause: `gh-issue-tracking:epic-implemented` + `epic`

## Epic implementation recorded — run the completion sequence, then loop to the next epic.
## Label-driven: matches on the `gh-issue-tracking:epic-implemented` + `epic`
## label combination. The triggering issue is the epic issue whose
## implement-epic run succeeded. This clause is the follow-on the reference
## file documents as deferred (init-success clause's NEXT STEP comment); its
## steps re-key the proven rev1 per-epic sequence (steps 2-4 plus the
## epic-complete loop) onto the rev2 label vocabulary.

- postStatusUpdate("🤖 Orchestrator matched `gh-issue-tracking:epic-implemented` + `epic` clause. Parsing epic from title...")
- $implemented_epic = extract_epic_from_title(title)
- if $implemented_epic is null or empty:
  - postStatusUpdate("❌ Could not parse epic identifier from issue title. Cannot proceed with PR review.")
  - comment on the issue with an error explaining the title could not be parsed, then skip to ##Final.

## Step 1/3: Review, approve, and merge all PRs for this epic
## This step handles: CI verification & remediation, code review delegation,
## auto-reviewer wait, PR comment resolution, and merge execution.
- postStatusUpdate("🤖 Step 1/3: Starting `review-epic-prs` for epic: " + $implemented_epic)
- /orchestrate-dynamic-workflow
    $workflow_name = review-epic-prs { $epic = $implemented_epic }
- if review-epic-prs fails:
  - postStatusUpdate("❌ Step 1/3 `review-epic-prs` failed for: " + $implemented_epic + ". See workflow run logs.")
  - skip to ##Final.
- postStatusUpdate("✅ Step 1/3: `review-epic-prs` completed for: " + $implemented_epic + ". Starting progress report...")

## Step 2/3: Report progress and capture action items
## Lightweight: report progress, flag deviations, note plan-impacting discoveries.
- postStatusUpdate("🤖 Step 2/3: Starting `report-progress` for epic: " + $implemented_epic)
- /orchestrate-dynamic-workflow
    $workflow_name = single-workflow { $workflow_assignment = report-progress, $epic = $implemented_epic }
- if report-progress fails:
  - postStatusUpdate("❌ Step 2/3 `report-progress` failed for: " + $implemented_epic + ". See workflow run logs.")
  - skip to ##Final.
- postStatusUpdate("✅ Step 2/3: `report-progress` completed for: " + $implemented_epic + ". Reviewing for action items...")
- Review the report for any ACTION ITEMS (deviations, new findings, plan-impacting issues).
- if ACTION ITEMS are found:
  - postStatusUpdate("⚠️ Action items found in progress report. Filing issues for newly-discovered work.")
  - File issues for newly-discovered required work.
  - Update descriptions of upcoming epics/phases if needed.

## Step 3/3: Debrief and document
- postStatusUpdate("🤖 Step 3/3: Starting `debrief-and-document` for epic: " + $implemented_epic)
- /orchestrate-dynamic-workflow
    $workflow_name = single-workflow { $workflow_assignment = debrief-and-document, $epic = $implemented_epic }
- if debrief-and-document fails:
  - postStatusUpdate("❌ Step 3/3 `debrief-and-document` failed for: " + $implemented_epic + ". See workflow run logs.")
  - skip to ##Final.

## Mark this epic complete
## The rev2 completion marker is the CLOSED epic issue (closing does not fire
## the `labeled` gate, so it costs no extra dispatch). The deprecated rev1
## `implementation:complete` label is deliberately NOT applied — it would
## re-enter the dispatch gate and burn a default-clause run.
- postStatusUpdate("✅ Epic " + $implemented_epic + " reviewed, reported, and debriefed. Closing this epic.")
- close this epic issue with a short comment indicating it is complete.

## Loop: pick the next unimplemented epic
- $next_epic = find_next_unimplemented_epic()
- if $next_epic is null:
  - postStatusUpdate("🏁 All epics are complete! The implementation plan is fully implemented.")
  - close the plan issue with a final comment "All epics are complete. The implementation plan is fully implemented."
  - skip to ##Final.
- postStatusUpdate("🤖 Next unimplemented epic found: #" + $next_epic.number + " — " + $next_epic.title + ". Starting `implement-epic`...")
- $epic_id = extract_epic_from_title($next_epic.title)
- if $epic_id is null:
  - postStatusUpdate("❌ Could not parse epic identifier from issue title (#" + $next_epic.number + "). Cannot proceed with implementation.")
  - comment on the issue with an error explaining the title could not be parsed, then skip to ##Final.
- /orchestrate-dynamic-workflow
    $workflow_name = implement-epic { $epic = $epic_id }
- if implement-epic succeeds:
  - postStatusUpdate("✅ `implement-epic` completed for epic #" + $next_epic.number + " (" + $epic_id + "). Applying `gh-issue-tracking:epic-implemented` label.")
  - apply label "gh-issue-tracking:epic-implemented" to that epic issue (issue number $next_epic.number) — its webhook fires the next iteration of this clause.
- else → postStatusUpdate("❌ `implement-epic` failed for epic #" + $next_epic.number + " (" + $epic_id + "). See workflow run logs."), skip to ##Final."""

_DEFAULT_CLAUSE = """\
## Matched clause: `(default)`

- postStatusUpdate("⚠️ Orchestrator: no clause matched for this event. Fell through to `(default)`. Event details printed to workflow log.")
- print the contents of your EVENT_DATA with a message stating no match was found so execution fell through to the
  `(default)` clause case.
## NOTE: the rev1 `orchestration:*` and `implementation:*` label namespaces
## are deprecated in this version — the rev2 state machine keys on
## `gh-issue-tracking:*`. Deliveries triggered by rev1 labels intentionally
## land here: report and end the turn, do not improvise a workflow."""

_DIRECT_BODY_CLAUSE = """\
## Matched clause: `gh-issue-tracking:direct-body`

## Direct-body dispatch — triggered by the gh-issue-tracking:direct-body label.
## NO workflow name is parsed and NO arguments are extracted. The ENTIRE issue
## body is passed VERBATIM as a prompt, so an issue carrying arbitrary
## commands/instructions can be dispatched by simply labeling it. Nothing in
## the body is interpreted as workflow syntax.
##
## SECURITY: direct-body is the widest dispatch surface (it runs arbitrary
## instructions with the orchestration token). The webhook receiver gates it
## to an explicit trusted-sender allowlist (env DIRECT_BODY_ALLOWED_SENDERS)
## BEFORE this clause can ever run — and the gate checks the issue's FULL
## label set, not just the triggering label, so a lingering direct-body label
## cannot bypass it via a later differently-labeled event. A dispatch reaching
## here was already authorized. The body must STILL be treated as untrusted
## content: never echo secrets, and prefer scoping work to the dispatching
## repo rather than cross-repo mutation.

- postStatusUpdate("🤖 Orchestrator matched `gh-issue-tracking:direct-body` clause. Running the issue body directly as a prompt...")
## Link the issue to the project board early (best-effort) so it is tracked
## even if the run fails mid-way (prevents orphaned issues). Discover the
## project via `gh project list --owner <owner> --limit 5` and
## `gh project item-add <num> --owner <owner> --url <issue-url>`. Skip
## silently if no project is found or the add fails — this must not block the run.
- Run the following issue body VERBATIM as your instructions — it IS the
  prompt. Do NOT parse a workflow name and do NOT wrap it in
  `$workflow_name = ...` syntax; just execute the slash-commands or arbitrary
  instructions it contains, exactly as written:

---BEGIN ISSUE BODY---
__ISSUE_BODY__
---END ISSUE BODY---

- if the body execution succeeds:
  - postStatusUpdate("✅ Direct-body execution completed.")
  ## PUBLISH & VERIFY — do NOT post "finished" or close until any work is
  ## reachable on the remote. Local commits that are never pushed trap the
  ## work inside the workspace.
  - Determine the working branch: `git rev-parse --abbrev-ref HEAD` in the project workspace.
  - If the branch is the default branch (`main` or `master`): SKIP publish (never push to the default branch). Log a warning and proceed straight to the close step.
  - Else if there is no `origin` remote (`git remote get-url origin` fails): SKIP publish. Log a warning that no remote is configured and proceed to the close step.
  - Else:
    - If `origin/<branch>` is absent OR `git log origin/<branch>..HEAD` is non-empty (there are unpushed commits): run `git push -u origin <branch>`.
    - If push fails: postStatusUpdate("❌ Direct-body succeeded locally but `git push` failed. The work is not on the remote. Leaving the issue open for retry."), then leave the issue open and skip to ##Final.
    - Verify a PR exists: `gh pr list --head <branch> --json number`.
      - If no PR exists: `gh pr create --head <branch> --title "direct-body: <summary>" --body "<derived from the issue>"`.
      - If PR creation fails: postStatusUpdate("❌ Branch pushed but `gh pr create` failed. Leaving the issue open for retry."), then leave the issue open and skip to ##Final.
  - post a final postStatusUpdate("🏁 Direct-body dispatch complete — finished with no errors.") then close the issue.
- if the body execution fails:
  - postStatusUpdate("❌ Direct-body execution failed. See details below:\\n{summary of failure reason and any potential next steps}")
  - leave the issue open."""


@dataclass(frozen=True)
class _Clause:
    """One row of the rev2 clause table.

    ``label`` is the exact trigger label (lowercase); ``requires`` are
    co-labels that must also be present on the issue (the old
    ``labels contains: X && labels contains: Y`` conditions). Selection is
    first-match-wins in table order — the reference file's rule, executed in
    code instead of by the model.
    """

    label: str
    requires: frozenset[str]
    body: str


_CLAUSE_TABLE: tuple[_Clause, ...] = (
    _Clause("gh-issue-tracking:init-success", frozenset(), _INIT_SUCCESS_CLAUSE),
    _Clause(
        "gh-issue-tracking:epic-implemented",
        frozenset({"epic"}),
        _EPIC_IMPLEMENTED_CLAUSE,
    ),
)

_TEST_DEBUG_MODES = """\
## Test and Debug Modes

If the issue or comment or other entity that triggered this workflow contains
the label or keyword `test` or `debug` also perform the following additional
steps:

- `test`:
  - Before executing the logic in the matched clause, print a message "TEST MODE: This is a test. The following logic would be executed:" followed by the logic that would be executed based on the matching clause. Then skip actually executing any logic and jump to the ##Final section.
- `debug`:
  - Before executing the logic in the matched clause, print a message "DEBUG MODE:" and increase the level of your logging and output of internal state information, including the content of relevant variables and the reasoning behind your decisions. Add any arguments or instruct any commands that you execute to increase their tracing and debug output levels as well. Then proceed to execute the logic as normal.
  - **As always, be careful to not print any secrets, API keys, passwords, or other sensitive information in the increased output in debug mode.**"""

_HELPER_FUNCTIONS = """\
## Helper Functions

These are reusable procedures referenced by the clause logic above. When the
clause calls one of these functions, execute the steps described here and use
the result.

### postStatusUpdate(message)

> Posts a status update comment on the triggering issue.
>
> **Input:** `message` — the status message string to post.
>
> **Steps:**
> 1. Extract the issue number from the EVENT_DATA (e.g. `event.issue.number`).
> 2. Post a new comment on that issue in the current repository using `gh issue comment <issue_number> --body "<message>"` or the equivalent GitHub API call.
> 3. Do not edit or replace any existing comments — always create a new comment.
>
> **Returns:** nothing.

### find_next_unimplemented_epic()

> Finds the next epic issue that has not yet been implemented. The epics exist
> as GitHub sub-issues of the main plan issue (created by
> /gh-issue-tracking-init).
>
> **Steps:**
> 1. Locate the main plan issue: the issue carrying the `plan` level label. In
>    the `gh-issue-tracking:init-success` clause the triggering issue IS the
>    plan issue; in the `gh-issue-tracking:epic-implemented` clause it is the
>    triggering epic's parent. Get its sub-issues via
>    `gh api repos/<owner>/<repo>/issues/<plan_number>/sub_issues` or the
>    equivalent GraphQL query.
> 2. Filter for sub-issues that carry the `epic` label (e.g.
>    `gh api ... | jq '.[] | select(.labels[].name == "epic")'`).
> 3. Sort the remaining epic issues by `number` ascending to preserve plan order.
> 4. For each epic issue in order:
>    - If the epic is OPEN (state `open`, not closed), this is the next
>      unimplemented epic. Return it.
>    - If the epic is closed, skip it and continue. (Closing the epic is the
>      rev2 completion marker — the epic-implemented clause closes each epic
>      it finishes; the deprecated rev1 `implementation:complete` label check
>      is deliberately not used.)
> 5. If **every** epic is closed, return `null` — there is nothing left to
>    implement.
>
> **Returns:** the `number` and `title` of the next unimplemented epic issue,
> or `null`.

### extract_epic_from_title(title)

> Parses the issue title to extract the epic identifier string.
>
> **Input:** `title` — the issue title (e.g. "Epic 3: Repository Layer").
>
> **Steps:**
> 1. Epic issues created by gh-issue-tracking-init follow the numbered-title
>    convention `Epic <N>: <Name>` — extract `<N>` and return it as the epic
>    identifier string (e.g. `3`).
> 2. If the title instead uses the legacy form (e.g. "Epic: Phase 1 — Task 1.2
>    — Data Modeling"), extract the phase number and line_item identifier from
>    the title text and return them as the identifier.
> 3. If neither form parses, return `null`.
>
> **Returns:** the epic identifier string suitable for passing to
> `implement-epic`, or `null`."""

_PUBLISH_VERIFY = """\
## Publish & verify

Publish results the way the in-repo workflows already specify: work on a
non-default branch, open or update a pull request, and post the outcome to
the issue (a status comment, plus any labels the clause applies to record
state). Never push to the default branch. Before declaring the work
finished, verify it is reachable on the remote (branch pushed, pull request
open). If the work fails or cannot be published, leave the issue open and
post a comment describing the failure and the next step."""

_FINAL = """\
## Final

Finish your turn with a short summary of what you found and did: which
clause matched, which workflows ran, what succeeded or failed, and which
comments/labels/pull requests you published. If a step failed, say what the
next run should pick up."""


_PROMPT_TEMPLATE = """You are the orchestration agent for the GitHub repository {repo}.

An accepted GitHub webhook delivery triggered this run:
- issue: #{number} {title}
- triggering label: {label}
- labels currently on the issue: {issue_labels}
- delivery id: {delivery_id}

Full webhook payload (EVENT_DATA, JSON):

```json
{event_data}
```

## Matched clause — mechanical execution

The clause below was selected mechanically from the rev2
`gh-issue-tracking:*` clause table: exact trigger-label match plus co-label
requirements, first match wins — the same match-clause state machine as the
vendored regression reference `orchestration_prompt.jinja2.md`, with the
selection done in code instead of by the model. Execute the clause's steps
exactly, in order, doing the same thing every time: do not substitute your
own plan for its steps, do not skip its status updates, and when a step
calls a helper function, execute that helper's procedure from the Helper
Functions section below and use its result. Each clause publishes its
outcome as tracking state (comments, labels, pull requests); the label
applications fire the next webhook deliveries, and the label cycle itself is
the state machine — never re-run a stage the tracking state already records
as done. Workflow definitions (`/orchestrate-dynamic-workflow` targets) live
in the external agent-instructions repo — fetch their current content at
runtime rather than assuming.

{clause_body}

{modes}

{helpers}

{publish_verify}

{final}"""


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


def _select_clause(label: str, issue_labels: list[str]) -> str:
    """First-match-wins clause selection — deterministic Python.

    The reference file's branching rule ("All mentioned values in the clause
    must match… First match wins… If no match is found, execute the
    ``(default)`` clause") executed as code: exact trigger-label match plus
    the clause's co-label requirements. Deprecated rev1 labels and anything
    else fall to the default clause.
    """
    n = (label or "").strip().lower()
    have = set(issue_labels)
    for clause in _CLAUSE_TABLE:
        if n == clause.label and clause.requires <= have:
            return clause.body
    return _DEFAULT_CLAUSE


_EMPTY_BODY_SENTINEL = (
    "Direct-body dispatch accepted for {repo}: the labeled issue #{number} "
    "carries an empty body, so there is no prompt content to run. Post a "
    "status comment on the issue explaining that the direct-body dispatch "
    "was empty, then end your turn."
)


def _clause_prompt(info: PromptInfo, clause_body: str) -> str:
    issue = _issue(info)
    return _PROMPT_TEMPLATE.format(
        repo=info.repo,
        number=issue.get("number", "(unknown)"),
        title=issue.get("title") or "(unknown)",
        label=info.label,
        issue_labels=", ".join(_issue_labels(info)) or "(none)",
        delivery_id=info.delivery_id,
        event_data=json.dumps(info.payload, sort_keys=True, indent=2),
        clause_body=clause_body,
        modes=_TEST_DEBUG_MODES,
        helpers=_HELPER_FUNCTIONS,
        publish_verify=_PUBLISH_VERIFY,
        final=_FINAL,
    )


def build_orchestration_prompt(info: PromptInfo) -> str:
    """Build the mechanical clause-table orchestration prompt for one envelope.

    Clause table (the reference file's rev2 rows; rev1 rows deliberately not
    ported — deprecated labels fall to ``(default)``):

    - ``gh-issue-tracking:direct-body`` — the issue body verbatim inside the
      clause's run/publish/close mechanics (sender gate already applied
      upstream in ``filters``); an empty body gets a sentinel direction so
      the agent reports it on the issue.
    - ``gh-issue-tracking:init-success`` — scan the Plan issue's sub-issues,
      implement the first unimplemented epic, apply ``epic-implemented``.
    - ``gh-issue-tracking:epic-implemented`` (+ ``epic`` co-label) — review /
      report / debrief the epic, close it, loop to the next epic or finish
      the plan.
    - anything else — the reference file's ``(default)`` clause: report that
      no clause matched and end the turn.
    """
    if _is_direct_body(info):
        body = _issue(info).get("body")
        if isinstance(body, str) and body.strip():
            clause = _DIRECT_BODY_CLAUSE.replace(_BODY_TOKEN, body)
        else:
            issue = _issue(info)
            return _EMPTY_BODY_SENTINEL.format(
                repo=info.repo, number=issue.get("number", "(unknown)")
            )
    else:
        clause = _select_clause(info.label, _issue_labels(info))
    return _clause_prompt(info, clause)
