# Rev2 State Map — Design Writeup + Sequenced Dev Plan

Status: **IN OWNER FEEDBACK — markup nearly complete, all feedback folded as of 2026-10-24
(blocks marked `**Feedback:**`, each with a `Folded` note beneath); ONE final owner pass pending
before approval. No implementation yet.** Baseline direction
approved in principle (owner 2026-10-24: "ok im sold — lets do C with a goal of adding D via the
swarm skill"). This doc is the implementation contract for the prompt rework, and the unified
order for the charlie68 follow-ups.

Companions:

- [`charlie68-incident-followups.md`](charlie68-incident-followups.md) — D1–D6, owner-decided
  2026-10-24. Reconciled with this plan in §5.
- [`restore-rev2-clause-table.md`](restore-rev2-clause-table.md) (on branch
  `dev/restore-rev2-clause-table`, PR #53 **draft**) — the mechanical design C replaces.
  §6 lists what carries over from it.
- [`skill-plan.md`](skill-plan.md) — the `/orchestrate-swarm` skill plan (the D endpoint).

---

## 1. The thesis — why "C" (mechanical knowledge, dynamic execution)

Two philosophies competed for the orchestration prompt:

- **Mechanical (rev2 clause table, PR #53 as-built)**: the prompt prescribes the procedure for
  every label. Proven across two old-stack revisions; deterministic; but it re-vendors 430 lines
  of template, un-simplifies the receiver, and re-couples it to workflow vocabulary.
- **Dynamic (Phase 3, shipped today)**: the prompt gestures at intent; the session figures out
  everything. Simple; swarm-pure; but every cold-started session re-derives the pipeline map from
  scratch, expensively.

The live record says the honest thing: **the same vague prompt, on the same state transition,
produced both the worst and the best run this stack has ever seen.**

| Run | Trigger | Prompt | Model/budget | Outcome |
|---|---|---|---|---|
| `0feb65c1` (kilo24, 10-18) | `init-success` | Phase 3 vague | paid GLM, 3.5 h ceiling-era | 3.5 h, 633 tool calls, **nothing published** |
| `7ad18141` (charlie68, 10-23) | `init-success` | Phase 3 vague | pinned GLM-5.3, 900 s idle | **6 h 50 m, Story 1.1 implemented end-to-end, PR #32 open, clean `end_turn`** |

Same direction text, same transition, opposite results — **variance is the enemy, and variance is
what underspecification buys.** And note what `7ad18141` achieved it *without*: v2 never read the
stamped `.opencode/opencode.jsonc`, so no `swarm-orchestrator` king, no agent roster — a solo
default agent re-derived the whole pipeline and executed it. That is the dynamic ceiling proving
itself, and it is genuinely impressive.

The mistake would be concluding "dynamic won" *or* "mechanical won." Split the problem:

- **Deciding** what to do, in what order, adapting to drift — the session's job. Keep it dynamic.
- **Knowing** the pipeline's states, transition contracts, and completion markers — shared
  knowledge that cannot be derived from live state and does not survive telepathy. Write it down
  once.

The telepathy proof is already on record: #53's Decision 8 pre-merge probe caught that an agent
handed an epic would pass the *title ordinal* ("Epic 3:") to `implement-epic`, which expects an
*issue number* — resolving the wrong epic or none. No amount of decision-making authority fixes
not being told what `$epic` means. Every webhook cold-starts a fresh session with no persistent
orchestrator — the durable state across runs is the issues, labels, and PRs, plus (owner
2026-10-24, folded below) the clone's own `.agents/memory.md` and `.agents/rules/`. The prompt is
where the pipeline's transition semantics live; memory and rules are where runs accumulate.

**C in one sentence:** replace the two vague direction paragraphs with one compact state map —
every fact the session cannot derive (vocabulary, contracts, markers, loop semantics, hard
warnings) and nothing it can (what exists, what's next, what's broken).

**D in one sentence:** once `/orchestrate-swarm` exists, the map moves into the skill (the king's
surface), and the receiver prompt shrinks to event context + "follow the canonical rev2 contracts"
— one canonical copy read by every entry point (dispatch, `$swarm`, the skill). C is structured to
make D a move, not a rewrite: the map is one standalone constant.

**Division of labor (owner 2026-10-24):** the state map says WHAT to do and WHEN; the clone's
`rules/<topic>.md` files say HOW (PR/merge policy, commits, testing, style); `.agents/memory.md`
records WHAT HAPPENED and what was learned. All three ship batteries-included in every stamped
clone — and the best run already used them unprompted: the 6h50m charlie68 session wrote its
Story 1.1 progress + a flagged ambiguity into the clone's `.agents/memory.md` and committed it
with its PR (`7646ad0`). The map's job is to make that behavior a contract instead of an
accident.

## 2. The state map (v2 draft — this text is the shipped artifact)

Replaces `_HIERARCHY_DIRECTION` and `_IMPLEMENTATION_DIRECTION` in
`src/webhook_receiver/prompt_builder.py`. Injected for all `gh-issue-tracking:*` (prefix) and
`implementation:ready|complete` (exact) labels. `gh-issue-tracking:direct-body` keeps its existing
verbatim-body path (unchanged since Phase 3; #53 Decision 3's wrapper compacted into the standing
mechanics below). All `orchestration:*` (rev1) labels keep the deprecated-note fallthrough
(#53 Decision 4).

```text
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
```

~85 lines replacing ~20 vague ones — versus 600+ ported clause lines under the mechanical design.
`prompt_builder` net growth over `main`: ~100 lines.

### Differences from the mechanical design (#53 as-built)

| #53 mechanical | C |
|---|---|
| Clause selection: exact per-label Python match, first-match-wins | Selection unchanged from Phase 3 (prefix + exact); the map's rows do per-label differentiation |
| Clause bodies: ~30 imperative procedure lines per label, near-verbatim from the vendored reference | One map: states + canonical next transition + contracts, no procedures |
| `find_next_unimplemented_epic` helper pseudo-function in prompt text | "lowest-numbered OPEN issue labeled `story`/`epic`" — a derivable rule, not a named helper |
| No story-level cycle (rev2 reference was epic-level) | Story-level rows (`implementation:ready`/`complete`) absorb **D6's autonomous PR cycle** |
| Loop enforced by clause text | Loop stated as the cycle + "one unit per run; the label you apply re-triggers the next run" |

## 3. Test strategy (the Phase 3 exit criterion inverts once, deterministically)

- **Contract-presence** (deterministic string asserts): every rev2 prompt contains the `$epic`
  ISSUE NUMBER warning, the loop statement, the one-unit-per-run rule, the closed-issue completion
  markers, the verify-first clause, publish & verify, the 3-round/`needs-owner` budget, and the
  durable-memory read/write clauses.
- **Row presence**: each rev2 state's canonical next transition appears in the prompt for its
  label class.
- **Row-format guard** (owner 2026-10-24): every state row carries the `(on the <labelled
  resource>)` qualifier and an on-completion transition naming the next label — the map's rows
  stay format-consistent.
- **Rev1 fallthrough matrix** (from #53, kept): every `orchestration:*` label → deprecated note.
- **direct-body** (unchanged since Phase 3/#53): verbatim embed + BEGIN/END markers + empty-body
  sentinel.
- **Absence guards**: retired helper names (`find_next_unimplemented_epic`,
  `extract_epic_from_title`, `postStatusUpdate`) never appear; no numbered step-list scaffolding
  (guard against clause bodies regrowing).

## 4. Sequenced dev plan

Stages are ordered by dependency, not size. Each carries a delegation brief
(Goal / Context / Constraints / Done-when); Constraints *name* the governing rules files rather
than restating them (`.agents/rules/delegation.md`). Every stage: full
[`validation.ps1`](../../validation.ps1) gate green before push (`.agents/rules/validation.md`),
`/safe-commit` before each commit, PR to `development` with milestone `maintenance`
(`.agents/rules/source-control.md`), Kilo threads replied+resolved, re-read thread state on the
head SHA before any merge; a PR merges only when ALL checks are GREEN + MERGEABLE with zero
unresolved threads — no path to resolution is the only escalation. Merges in THIS repo are
owner-gated; clone PRs under the D6 cycle merge autonomously per the map's gate.

**Feedback:**  

- Invoking the auto review agents and/or then waiting for them to finish, before starting to review I think could get tricky- So we could alternatively dispatch 2-3 subagents to perform review with comments for found issues, then /`resolve-pr-comments` until UNRESOLVED comment thread <= 0 + all workflows GREEN (otherwise perform `/fix-failing-workflows` , re-read thread state on the head SHA before any merge, merge owner-gated. PR MUST BE ALL GREEN + MERGABLE, otherwise no merge and escalate (only if there are no paths to resolution)

- Agree. esp with "done-when". Providing the few small key contraints will be the difference between successful high-level deterministic sequenced runs and chaos. Need to make sure the that these headings are consistent and correct.

Also, I saw sometihng that really got me thinking.  
  
1. The `rules/memory.md` mechanism. I think we should use this same mechnism that we already use in the context templates so that the orchestator has an inter-session run durable memory. It doesnat have to save every detail, but some jey facts and maybe progress context, like it does now when it writes down what it has completed would be reall y uself. Also it can self-improve if we make a rule file entry about noting things that went wrong or it had trouble with and the solution it finallyt kanded on. So as it goes alkong it learns to avoid the gotchas and foot guns it has previsouly run into.  
2. We keep the `rules/<rule-topic-file>.md`, as conventions and policies, style, etc. Th state map contraints tell it was to do and when to do it, but the rules tell it how to do things, e.g. PR/merge poicies, commit policies, testing policies, etc. Betwenen the two + memoiry I think we would really have a powerful system.  

And the best ting is, IIRC, the rules and memory system come batteris include din the template clone.

> **Folded (2026-10-24, this session):** agreed on all three points, and verified first-hand —
> the clone ships `.agents/memory.md` + 8 rules files + skills, and the 6h50m run ALREADY used
> the mechanism unprompted (it wrote its Story 1.1 entry + a reviewer flag into the clone's
> memory.md and committed them with its PR, `7646ad0`). Folded as: the §1 division-of-labor
> paragraph; the map's two new rows — "durable state (orient from it first)" and "durable
> learning (write before you end)" — replacing the old "previous runs left no memory" line,
> which would have actively suppressed the mechanism; memory contract-presence tests (§3); a
> Decision 11 in the Stage 3 plan-doc work; and a memory-poisoning risk entry (§7). Mechanics
> chosen (flag if you want them different): memory rides the run's PR; runs that open no PR
> (epic rollups) commit `.agents/` bookkeeping directly to the default branch — bookkeeping
> only, never work product.
>
> **Folded (2026-10-24, round 2 — the review-flow + headings bullets above):** (1) the review
> flow is re-specified with no wait-for-reviewers step: dispatch 2–3 subagent reviewers that
> post comments directly, then `/resolve-pr-comments` until unresolved threads = 0,
> `/fix-failing-workflows` until green, re-read thread state on the head SHA, merge only on ALL
> GREEN + MERGEABLE, escalate only with no path to resolution — folded into the map's
> `implementation:complete` row, the §4 intro gate wording, and Stages 3–4. (2) Heading
> consistency: every stage brief now carries the uniform Goal / Context / Constraints /
> Done-when / Delegate set (Stages 4–5 gained their missing headings), and the map's state rows
> now follow your row format — `<label> (on the <labelled resource>) — context and instructions
> → on completion, the label that advances the cycle` — recorded in §2 and pinned by the §3
> row-format guard. (Your `//` format comment was lifted out of the map body so it doesn't ship
> to sessions.)

### Stage 0 — Pre-flight (done + one owner action)

- **DONE (2026-10-24, this session): `ACP_IDLE_TIMEOUT=900` uncommented in `.env`** — the 15-min
  idle window now survives restarts (the running unit already had it active; no restart needed).
- **D7 (NEW finding, this session — owner action): the 16:57:18Z `implementation:complete` label
  event on charlie68 #10 NEVER reached the receiver** (journal-verified: zero webhook receives
  16:53–17:20 UTC; endpoint proven healthy at 17:39 by other org deliveries; API check needs
  `admin:org_hook`). **Check org Settings → Webhooks → the org hook → Recent Deliveries around
  2026-10-23 16:57 UTC.** If absent there too, the Issues checkbox was likely flipped mid-day
  10-23 — re-check it and redeliver. This is the exact mechanism D6's cycle depends on; it must be
  understood before Stage 4 acceptance means anything. Understanding only — dead runs are NOT
  recovered (owner 2026-10-24: seed clones are testing artifacts; see §7 item 4).
- **Rider for the first service PR (test hygiene)**: pin `ACP_TRACE_ROOT` to `tmp_path` in the
  `trace_log`/`acp_host` tests — this morning's two gate runs dropped 8 fixture run dirs
  (`owner/repo`, `RuntimeError: boom`) into the live observability surface (known
  Remember-To-Do).

### Stage 1 — D1 + D3: driver liveness + chunked apply + case guard (parent-template PR)

- **Goal**: dispatched `gh-issue-tracking-init` runs never die to the idle watchdog mid-apply, and
  generated drivers can't hit PowerShell case collisions.
- **Context**: charlie68 run `df4c8f2d` was killed at 302 s mid-board-onboarding — the apply is
  ONE redirected bash call (`> apply-runN.log 2>&1`), so neither liveness signal (session updates,
  stderr lines) fires. `$Num`/`$num` collision broke `07-execution.ps1` (run `8a809037` self-fixed
  it live). Owner feedback (2026-10-24): the acceptance bar is the OLD watchdog's trustworthiness
  — the frozen `orchestrator-service` (@`2bd6d06`, `webhook_receiver/watchdog.py`) took several
  iterations to reliably tell a dead session apart from the relative silence of a subagent
  delegation or a long tool call. Current signal taxonomy: session updates (PR #50), harness-log
  stderr lines (PR #50 — also where subagent-delegation activity shows: the 6h50m charlie68 run
  streamed harness lines continuously while working), and driver-emitted progress (this stage).
  The one proven blind spot is the redirected silent apply (D1's case).
- **Constraints**: `.agents/rules/validation.md` (parent gate), `.agents/rules/source-control.md`
  (parent PR flow), `.agents/rules/coding-style.md`. Changes land in **swarm-context**
  (`.agents/skills/gh-issue-tracking-init/` + driver templates) word-for-word per
  `.agents/rules/lifecycle.md`; keep a tee-style apply log for forensics.
- **Done when**: a fresh tracking-init dispatch completes board onboarding with
  `ACP_IDLE_TIMEOUT=300` in effect, end to end, watchdog never firing; next seeded clone's drivers
  use `$IssueNum`-style distinct names (charlie68 doc D1/D3 done-when); and a delegation-heavy run
  (subagent review per D6) stays alive through a >idle quiet delegation — the silence-vs-dead
  distinction the old `orchestrator-service` watchdog earned.
- **Delegate**: `swarm-implementer` (parent checkout worktree per `.agents/rules/practices.md`).
- **Note**: the 900 s window (Stage 0) removes the urgency cliff; this remains first because it is
  the durable fix and the cheapest.

### Stage 2 — D2/S1 + D4: v2-shaped config stamping + fallback canary (service + parent PR)

- **Goal**: dispatched clones resolve the pinned model (`zai-coding-plan/glm-5.3`, O1) from their
  own stamped root `opencode.json`; the receiver fails loudly on fallback-model resolution.
- **Context**: opencode v2 ignores `.opencode/opencode.jsonc` — the stamped clone config (and the
  king `default_agent`!) is dead config; post-strip sessions fell to version-dependent defaults
  (v2.1.3 = authless `flint-40b-free` → 3 dead runs, 10-23). Already-approved plan:
  [`opencode-v2-config-migration.md`](opencode-v2-config-migration.md) S1 (epic #42 story #43).
  **Stage 2 silently revives `default_agent: swarm-orchestrator` + the agent roster in v2 — it is
  the prerequisite for D6's "delegate review to subagents."**
- **Constraints**: `.agents/rules/validation.md`, `.agents/rules/source-control.md`,
  `.agents/rules/zcode-config.md`-adjacent (never derive client config syntax — use known-good
  examples), `.agents/rules/lifecycle.md` (parent mirrors word-for-word; `strip-model-settings.ps1`
  updated for the root-`opencode.json` layout). D4 canary mechanism proposal: detect
  fallback/free-tier resolution at spawn (e.g. `opencode debug config` probe) or by first-usage
  signature (size 262144 + cost 0.0), warn loudly + event; test-pinned.
- **Done when**: fresh clone's `opencode debug config` shows the root doc + pinned model; a
  hand-run session picks the pin; receiver logs a clear warning on fallback resolution (test);
  host-global pin removed after S1 verified (keep as rollback).
- **Delegate**: `developer` (service) + `swarm-implementer` (parent surfaces), one PR each side.

### Stage 3 — C: the state-map rework (branch `dev/restore-rev2-clause-table`, PR #53)

- **Goal**: ship the §2 map; PR #53 flips from mechanical to C.
- **Context**: everything in this doc. **New branch `dev/rev2-state-map` off `development`, new
  PR** (owner 2026-10-24: #53 and `dev/restore-rev2-clause-table` stay for posterity; cutting the
  new branch clean off `development` makes the PR's diff pure C — the mechanical detour lives only
  in #53's history). The 2 open Kilo SUGGESTION threads on #53 are moot there; expect fresh
  review on the new PR.
- **Constraints**: `.agents/rules/validation.md`, `.agents/rules/coding-style.md` (Simplicity
  First — the map is ONE constant, no selection rewrite), `.agents/rules/source-control.md`.
  Work items:
  1. Create the plan doc on the new branch (this design doc adapted, or landed as-is); add
     Decision 9 (mechanical knowledge / dynamic execution, owner 2026-10-24) + Decision 10
     (story-level cycle absorbed from D6; one-unit-per-run; O2/O3 gates) + Decision 11 (durable
     memory + the map/rules/memory division of labor).
  2. `_REV2_STATE_MAP` constant replaces `_HIERARCHY_DIRECTION` + `_IMPLEMENTATION_DIRECTION`;
     selection logic untouched; direct-body path untouched; the vendored reference committed
     fresh at `docs/reference/orchestration_prompt.jinja2.md` (byte-identical from
     `orchestrator-service`@`2bd6d06`; provenance note in the plan doc — nothing at runtime
     reads it).
  3. Tests per §3; keep #53's `acp_smoke`/e2e re-keying (Decision 7).
  4. Docs: architecture.md/usage.md direction sections; plans README index entry for this doc.
  5. Gate narrowing (owner 2026-10-24, allow-only confirmed): drop `orchestration:` from
     `_LABEL_PREFIXES` in `filters.py` (+ tests: rev1 labels filtered, rev2 dispatches). The
     gate's three existing allowlists stay; from here on, every new trigger vocabulary or event
     type dispatches exactly when we deliberately add it to the allowlist.
- **Done when**: full gate green; every §3 assertion passes; pre-merge probe — one real-opencode
  `acp_smoke` on an `init-success` envelope shows the session quoting the map's contracts
  (issue-number rule, one-unit rule) in its plan.
- **Delegate**: `developer` for `prompt_builder`+tests; `swarm-reviewer` pre-PR cold review.

**Feedback:** Lets leave`dev/restore-rev2-clause-table`, PR #53 for posterity, clone them, and do this work in the new branch+ new PR.

> **Folded (2026-10-24, this session):** agreed — #53 and its branch stay as-is for posterity
> (draft). One mechanics choice made explicit: the new branch `dev/rev2-state-map` is cut from
> `development`, NOT from the mechanical branch, so the new PR's diff is pure C instead of
> mechanical-plus-shrink; carry-over is content-level per §6 (Decision 8 contracts re-embedded,
> the vendored reference committed fresh at `docs/reference/`, Decision 7 re-keying re-applied).
> Override if you wanted the literal clone lineage instead.

### Stage 4 — Live acceptance: the charlie68 cycle (C + D6 done-when, merged)

- **Goal**: prove the autonomous loop end to end on `intel-agency/gap-miner-v2-charlie68`.
- **Context**: PR #32 (Story 1.1) is open, all 5 checks green — under O3 it is mergeable now;
  the owner may merge it by hand to start, or let the first `implementation:complete` dispatch
  drive it. Then: story 1.2 → … → epic 1 closes → next epic, no human re-fire. Requires Stage 0's
  D7 answer (deliveries flowing), Stage 2 (roster loads for subagent review), Stage 3 (the map).
- **Done when**: at least one full story cycle (complete → review → merge → next `ready`) and one
  epic rollup run with zero human steps; the park path exercised or at minimum test-pinned.
- **Owner decisions at this stage**: merge authority mechanism for the session (full `mode:
  primary` vs PAT-mediated — D6's open mechanism choice); **hard per-run ceiling: YES (owner
  2026-10-24), `ACP_PROMPT_TIMEOUT` value chosen here** (e.g. 24 h). The deeper acceptance bar is
  the old `orchestrator-service` watchdog's trustworthiness (owner 2026-10-24): kill what is
  dead, never what is quietly delegating — the taxonomy lives in Stage 1.
- **Constraints**: `.agents/rules/practices.md` (verify every claim first-hand — manifests,
  journal, live issue state; never agent self-report), `.agents/rules/source-control.md` (the
  merge ritual governs this repo's PRs; clone PRs merge per the map's own gate).
- **Delegate**: primary session drives; `swarm-verifier` collects the pass/fail evidence.

**Feedback:** Yes a hard upper-limit is good. But what we need is the effectiveness trhat the watchdog timer frokm the version, `workflow-orchestrator-service`(? or is `orchestration-service`). It was reliablew enouggh to be able to kill the session when x number of s wityhout activitry had passed, but also was smart enought to tell a dead session apart from the realtive silience that a subvagent delegation (or tool call) looks like. In other words it was trustowrtyh to kill it when it needed but not when it shouldnt. It did take *several* iteraitojns to getr there though. Getting a liveness signal from the subagent delegations was the most difficult part.

> **Folded (2026-10-24, this session):** agreed — and to answer the name question: the repo is
> **`orchestrator-service`** (frozen @`2bd6d06`; the watchdog was `webhook_receiver/watchdog.py`:
> idle + hard ceiling + 30 s poll, heartbeat via opencode server-log mtime — the old-stack
> prior-art rule holds again). It was never ported because its liveness signal belonged to the
> stderr-observation path Decision 7 deleted; PR #50 rebuilt the concept on session updates +
> stderr lines. On the hardest part you named — subagent-delegation silence: in the new stack,
> delegation activity surfaces as harness-log stderr lines (evidence: the 6h50m run streamed
> them continuously while working), so the signal likely exists already — but that is a claim
> to VERIFY in Stage 1's done-when (a delegation-heavy run surviving a >idle quiet delegation),
> not assume. Folded as: Stage 1 signal taxonomy + that done-when clause; Stage 4 ceiling
> (YES, value TBD) + trustworthiness bar.

### Stage 5 — D endpoint: `/orchestrate-swarm` skill (owner-gated start)

- **Goal**: re-home the map into the skill; receiver prompt shrinks to event context + pointer.
- **Context**: skill-plan.md fully answered (2026-09-25, zero code). Shared surface — mirrors to
  swarm-context per `.agents/rules/lifecycle.md`; update its taxonomy table (stale after Stage 3)
  as already noted. `swarm.md`'s run-state conventions apply.
- **Done when**: skill exists, dispatch prompt carries the pointer, one interactive `$swarm` run
  and one dispatch run both resolve the SAME map copy.
- **Constraints**: `.agents/rules/skills.md` (Agent Skills spec compliance; prefer scripts over
  prose), `.agents/rules/lifecycle.md` (parent mirror word-for-word — shared surface),
  `.agents/rules/validation.md`.
- **Delegate**: `developer` (skill + receiver shrink) + `swarm-implementer` (parent mirror).

## 5. Reconciliation with charlie68-incident-followups (D1–D6)

| Item | Verdict | Where it lands |
|---|---|---|
| D1 driver liveness + chunked apply | Agree, as written | Stage 1 (parent PR) |
| D2 model selection via migration S1 | Agree — research verified first-hand; S1 is the owner's remembered design | Stage 2 |
| D3 case guard | Agree, cheap, same PR | Stage 1 |
| D4 fallback canary | Agree; mechanism left open — proposal in Stage 2 | Stage 2 |
| D5 commit hygiene | Done (c1a2e06, 5ff8461, cb2fc92, cc876c9; `.qoder/` remains owner's call) | Closed |
| D6 autonomous PR cycle | Agree with the owner's O2/O3 decisions — **amended: D6's direction work rides Stage 3's map (rows + contracts), NOT a separate `prompt_builder` rewrite**; two sequential prompt rewrites would rework each other | Stages 3+4 |
| (new) D7 missing label delivery | This session's finding — owner checks org hook deliveries ~16:57 UTC 10-23 | Stage 0 |

The doc's suggested order (D1+D3 → S1/D4 → D6) is preserved with one amendment: **D6's landing
surface is Stage 3's map**, and its live exercise is Stage 4.

## 6. What carries over from #53 (content-level — C starts a fresh branch)

Per owner direction (2026-10-24), #53 and `dev/restore-rev2-clause-table` stay for posterity;
`dev/rev2-state-map` starts clean off `development`, so carry-over is content, not commits:

- Decision 8 contracts (from `69f8983`) — re-embedded verbatim in the map (all four).
- The vendored reference — committed fresh at `docs/reference/orchestration_prompt.jinja2.md`
  (byte-identical from `orchestrator-service`@`2bd6d06`); regression checklist + provenance
  only, never shipped prompt text.
- Decision 7 (smoke surfaces re-keyed to `gh-issue-tracking:init-success`) — re-applied.
- Plan-doc Decisions 1–8 per the fate table (1,2,4,5,6,7,8 survive; 3 compacted; new 9–11).
- The doc corrections to architecture.md / usage.md / receiver README — re-applied.

Nothing needs deleting: the clause-body port and the 294-line fidelity matrix live only
in the posterity branch (PR #53) and never reach `development`.

## 7. Risks & open questions (owner-gated)

1. **Cost/time of the autonomous cycle** — one productive run was 6 h 50 m on paid GLM-5.3. The
   one-unit-per-run contract bounds each run; **a per-run hard ceiling is DECIDED (owner
   2026-10-24) — the `ACP_PROMPT_TIMEOUT` value is chosen at Stage 4** (e.g. 24 h).
2. **Merge authority mechanism** (D6's open choice) — decide at Stage 4.
3. **Gate vocabulary — DECIDED allow-only (owner 2026-10-24)**: the pipeline already dispatches
   through three allowlists, verified in `filters.py`: event type (only `issues`, `:71`),
   trigger label (`_LABEL_PREFIXES = ("orchestration:", "gh-issue-tracking:")` + exact
   `implementation:ready|complete`, `:25`), and the fail-closed
   `DIRECT_BODY_ALLOWED_SENDERS` list for direct-body (`:45`). The one over-wide entry is the
   deprecated rev1 `orchestration:` prefix — it still passes and burns a default-clause run
   per label. Fix = Stage 3 work item 5 (drop the prefix); from then on every new trigger or
   event type dispatches exactly when we deliberately allowlist it.

   **Feedback: They shouldn't- what type of filters do we have in place between events coming in from the webhook (and other vectors) and the dispatch queue or sent to down to the client? Do we have a blacklist? Should we implement an allow-only whitelist? Whitelist seeems right here, bc we could ensure no events make it through execpe  and until we add those to the allowlist. This would allow us to carefully choose exactly when we ant to support a given/new event, even while having the pipeline completely implemnted.**

   > **Folded (2026-10-24, this session):** answered with the live filter inventory (item 3 above,
   > verified in `filters.py` first-hand) — three allowlists already exist; there is no blacklist.
   > Your allow-only direction is confirmed and folded: the deprecated `orchestration:` prefix is
   > the only over-wide entry, removed as Stage 3 work item 5, with the deliberate-addition rule
   > (new events/labels dispatch only when we choose to support them) recorded. The stray
   > duplicate numbering left at this item is cleaned up.

4. **D7 delivery-loss class** — understand the CAUSE (Stage 0's org-hook delivery-log check;
   D6 depends on deliveries flowing), but **do NOT recover dead runs (owner 2026-10-24): seed
   clones are testing artifacts, not real attempts at valuable apps — dead runs stay dead;
   manual recovery-by-relabel becomes a concern only once the system is declared working and
   released.**

   **Feedback:** if you're saying to go back and re-fire previous seed app clones so they continue their run- DON'T worry about them. All dead runs stay that way- no need to recover any of them. They are testing artifacts notrhing more- they werent real attempts to create valuable apps. Only once the system is declared working and "released" do we start caring about reciveriung dead runs manually by re-labelling etc.

   > **Folded (2026-10-24, this session):** folded into item 4 as written — no recovery of dead
   > runs; the D7 delivery-log check remains about understanding the failure class (D6 depends on
   > label deliveries actually arriving), not about resurrecting runs.

5. **Memory poisoning / drift (new, with the durable-memory fold)** — a wrong lesson recorded
   in the clone's `.agents/memory.md` becomes load-bearing for every future run, and the D6
   cycle merges without a human curator. Mitigations: entries stay factual + dated; lessons
   that should govern future runs land as rules-file edits riding a PR through the review
   loop, not as bare memory; `needs-owner` remains the escape hatch.
