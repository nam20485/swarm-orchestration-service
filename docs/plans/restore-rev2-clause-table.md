# Restore the mechanical rev2 clause-table orchestration prompt

Status: IN PROGRESS (2026-10-19; branch `dev/restore-rev2-clause-table`, owner-directed in-thread)
Date: 2026-10-19
Owner direction (verbatim, 2026-10-19): *"i dont want it to be dynamic- i want it be mechanical and do the sametihng evertytime. the old system worked well and was proven through 2 working revisions of the architecture"*; on vocabulary: *"`orchestration:*`, e.g. `orchestration:plan-approved` is the rev1 labels, not what we want to use here. `gh-issue-tracking:*`, e.g. `gh-issue-tracking:init-success` is the rev2 label style- this is what we want to use now in this version"*; on the cycle: *"it should loop … Then -> we loop back around to pick the next epic."*
Supersedes: [`completed/orchestrator-service-simplification.md`](./completed/orchestrator-service-simplification.md) §3.3 (the Phase 3 open-ended prompt) and the integration note it came from (`orchestrator-service-integration.md` item 1)
Regression reference: [`src/webhook_receiver/orchestration_prompt.jinja2.md`](../../src/webhook_receiver/orchestration_prompt.jinja2.md) — vendored byte-identical from `nam20485/orchestrator-service` @`2bd6d06`; committed by this change (previously it existed only as an untracked file in the owner's primary checkout)

## 1. Why

The 2026-10-19 forensic finding (memory, Current Activity): the `gh-issue-tracking:init-success` marker — the pipeline's designed next-step transition — passes the gate and enqueues a run, but Phase 3 collapsed every `gh-issue-tracking:*` label into one class-level prose direction, losing the old clause's mechanics (epic scan, `implement-epic` invocation, `epic-implemented` stamp). First live exposure (kilo24 → run `0feb65c1`) burned 3.5 h / 633 tool calls on vague direction. The owner reversed the Phase 3 principle: the state machine must be mechanical, keyed to the rev2 vocabulary, and loop.

## 2. Design

- **Clause SELECTION is deterministic Python**: exact trigger-label match plus co-label requirements, first-match-wins — strictly tighter than the reference file, which had the LLM scan the clause table itself.
- **Clause BODIES are ported near-verbatim** from the reference; rev2 rows only.
- **The label cycle is the state machine**: each clause publishes the next state (comments, labels, PRs); the applied label's webhook re-triggers dispatch. `filters.py` is untouched — the fix is direction fidelity, not gate suppression.

| Trigger | Clause (provenance) | Publishes |
|---|---|---|
| `gh-issue-tracking:direct-body` | run the issue body verbatim inside the ported status/board-link/publish&verify/close mechanics (reference :313-367); sender allowlist gate unchanged in `filters.py` | the body's outcome — e.g. `/gh-issue-tracking-init` applies `init-success` to the Plan issue |
| `gh-issue-tracking:init-success` | reference :369-401 with the canonical-contract handoff (Decision 8): `find_next_unimplemented_epic()` → `/orchestrate-dynamic-workflow implement-epic { $epic = $next_epic.number }` | `gh-issue-tracking:epic-implemented` on that epic |
| `gh-issue-tracking:epic-implemented` + `epic` | the follow-on the reference documents as deferred (:395-399), re-keying rev1 steps 2-4 (:204-272) + the epic-complete loop (:148-176): `review-epic-prs` → `report-progress` (+ action items) → `debrief-and-document` → close epic → **LOOP**: scan → `implement-epic` → apply `epic-implemented`; none left → 🏁 fully implemented, close the Plan issue | the next `epic-implemented`, or the terminal state |
| anything else gate-matched (incl. ALL rev1 `orchestration:*`, `implementation:*`) | reference `(default)` clause (:403-408) + a rev1-deprecation note | a "no clause matched" status comment, then the turn ends |

Helpers ported as prompt-text procedures (LLM-executed, as in the reference): `postStatusUpdate`, `find_next_unimplemented_epic`. The `test`/`debug` label modes are ported. Not ported: the rev1-only helpers (`find_next_unimplemented_line_item`, `parse_workflow_dispatch_body`) and `extract_epic_from_title` (retired by Decision 8).

## 3. Decisions

1. **Loop, not halt** (owner): after an epic completes, the clause scans for and implements the next unimplemented epic until the plan is fully implemented.
2. **Completion marker = the closed epic issue** (design): the reference helper skipped epics labeled `implementation:complete` — a deprecated rev1 label which, applied, re-enters the gate and burns a default-clause run per epic. Closing fires `issues.closed`, which the gate filters. The helper is re-keyed to skip closed epics.
3. **direct-body keeps its clause wrapper** (design): Phase 3 returned the bare body as the whole prompt; the reference clause wraps it in mechanical hygiene (status comments, best-effort board link, publish & verify, close-on-success). The wrapper is ported; the body still rides verbatim between `---BEGIN/END ISSUE BODY---` markers.
4. **No rev1 clauses** (owner): deprecated labels fall to `(default)`. Gate narrowing (stop dispatching them at all) is a separate owner decision — skill-plan.md scoped it out.
5. **Memory-graph machinery stripped** (repo rule): the reference's mandatory `search_nodes` startup and memory-write finale were discontinued in this repo (`.agents/rules/tools.md`, 2026-09-12); `##Final` becomes a plain run summary.
6. **Phase 3 discovery prose dropped** (design): the new-app-vs-existing-feature section and the "decide from live tracking state" progression language are the reversed principle; the direct-body kickoff issue carries explicit instructions instead.
7. **Smoke surfaces re-keyed to rev2** (design): `acp_smoke` default label → `gh-issue-tracking:init-success` (was deprecated `orchestration:plan-approved`); `scripts/e2e-orchestration.ps1` scenario 1 likewise.
8. **Epic handoffs carry the epic ISSUE NUMBER** (design; found by the pre-merge probe, verified first-hand against `nam20485/agent-instructions`): the canonical contracts are `implement-epic` `$epic` = "Epic issue object or issue number" (`getepic(15, …)` → issue #15), `review-epic-prs` `$epic` likewise, and `single-workflow` takes `$workflow_assignment` + `$assignment_inputs` (not the reference's flat `$epic = …`). The reference's `extract_epic_from_title` handoff is rev1 legacy — with rev2 numbered titles the `Epic <N>:` ordinal is NOT the issue number (kilo24: Plan #2, epics #3–31), so passing it would resolve the wrong issue or none. The helper is retired; clauses pass `$next_epic.number` / the triggering issue's number, and status text uses `#<number> — <title>`.

## 4. Tests

The Phase 3 exit criterion is INVERTED: `test_no_next_label_chaining_anywhere_in_matrix` (no prompt may name another matrix label) is replaced by clause-fidelity tests that REQUIRE the chaining — the label cycle is the state machine. Matrix: clause selection per trigger (incl. co-label miss → default); every rev1 label → default; direct-body verbatim embed + brace-safety + empty-body sentinel; helper procedures present; mechanical-execution preamble present; open-ended language + discontinued machinery absent; determinism, minimal-payload tolerance, and EVENT_DATA-JSON tests retained. `test_app.py` / `test_acp_smoke.py` prompt-content assertions updated to the same contract.

## 5. Validation & rollout

- Full `validation.ps1` gate (build → scan → test; python pytest + coverage > 85%; e2e simulator).
- Pre-merge probe: one real-opencode `acp_smoke` on the default init-success envelope. **Result (2026-10-19):** the dispatched session received the clause prompt and engaged it mechanically — quoting the clause's steps verbatim in its reasoning — and surfaced the `$epic` contract ambiguity now fixed by Decision 8. The probe did not reach `end_turn` within the operator's 25-minute bound (the session went meta against the fake `owner/repo` target, whose `gh` lookups cannot succeed); a clean end-to-end probe against a live dispatch repo is the merge-time acceptance step.
- PR to `development` with milestone + board; merge owner-gated.
- **Owner-checkout note**: the primary checkout holds an UNTRACKED byte-identical copy of `src/webhook_receiver/orchestration_prompt.jinja2.md`; remove it before pulling this branch's merge or git will refuse the overwrite.

## 6. Follow-ups (not in this change)

- `docs/plans/skill-plan.md`'s taxonomy table cites the Phase 3 label classes (`prompt_builder.py:206-215`) — stale after this change; update when that plan is implemented.
- Gate narrowing for deprecated rev1 labels (their deliveries currently dispatch a default-clause run each).
- A rev2 "named workflow + args" dispatch label (the old `orchestration:dispatch` clause's capability) — needs a vocabulary addition; `direct-body` covers kickoff today.
