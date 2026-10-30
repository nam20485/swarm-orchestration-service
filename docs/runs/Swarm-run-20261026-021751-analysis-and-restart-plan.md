# Swarm run run-20261026-021751 — analysis & restart plan

Companion to [`Swarm-run-20261026-021751-abort-report.md`](Swarm-run-20261026-021751-abort-report.md)
(the run's own debrief). Every claim below was verified first-hand from this session:
PR checks/diffs via `gh`, branch/worktree state via git, the port squatter via
`systemctl`/`curl`, the model pin via the contents API, memory files read directly.

---

## 1. Narrative & analysis of the run

Run `run-20261026-021751` initialized 2026-10-25 19:17 PDT against the 8-clause goal
(Stages 0–3 of [`docs/plans/rev2-state-map-design.md`](../plans/rev2-state-map-design.md)),
4 subagents spawned, round 1 only, aborted by owner directive at 19:48 (31 min wall).

Timeline: orientation (baseline gates both repos → discovered the local e2e blocker
and the #53 reference-fidelity issue) → wave 1 = three parallel implementers in
isolated `/tmp/kilo/*/wt/` worktrees (Stage 1 parent, Stage 2 parent, Stage 3 service)
→ Stage 1 done, pushed, PR swarm-context#12 → Stage 2 parent done; orchestrator cold
review caught the dropped MCP `{env:…}` auth headers; same worker resumed, fixed
(`ea8aea1`), pushed, PR #13 → both `development`s advanced mid-run (service: the
charlie68 companion doc `7f8e16a`/`5c88819`; parent: `5d990b0`) → wave-2 Stage 2-service
worktree cut from the advanced head, worker just launched → abort directive → workers
stopped, state finished `stopped`, findings written to memory + this debrief.

**What went well (verified):** clean abort mechanics (no merges, no default-branch
pushes, worktrees preserved, dense accurate memory); the cold-review catch on MCP
headers was a real defect found and fixed by the run itself; the port-8765 diagnosis
is fully corroborated (`e2e-orchestration.ps1` defaults `-Port 8765`; `mcp-agent-mail`
systemd **user** unit active; its `/health` answers `{"status":"ready"…}` — exactly
the assert-failure signature); both PRs are mechanically green (validate + droid-review
PASS, droid skipping) and MERGEABLE with zero threads.

**What the narrative overstates:** "Stage 1 completed, was verified" and both PRs in
"merge-ready shape" conflate *gate-green* with *done-when*. Neither stage's empirical
acceptance clause ran (see issues 5–6), and PR #13 carries a real correctness defect
the run's verification missed (issue 5). "Budget used 5 of 50" — `state.json` says
`spawned: 4`.

**Meta-lesson for the restart:** the goal's clause 4 ("all present checks GREEN +
MERGEABLE + zero unresolved threads") is necessary-but-not-sufficient — it certified
mechanical readiness while a wrong model pin sat in an all-green PR. The restart
prompt must name the O1 pin value explicitly so verifying it is a clause, not luck.
Also: my own earlier "he's polluting #53" call was wrong — the posterity branch has
zero new commits (all three date to 10-19); the run was *reading* it per §6 and
surfaced a genuine fidelity problem.

## 2. Issues

### A. Agent-encountered (all four verified true)

1. **Local e2e blocker (environmental)** — `mcp-agent-mail` permanently squats
   127.0.0.1:8765 (e2e default). Verified. Durable fix (free-port walk) correctly
   routed to Stage 2's service PR; CI runners are clean so PR checks stay
   authoritative; script already takes `-Port` for local workarounds.
2. **#53's vendored reference is not byte-identical** — claimed one edited line
   ("token + --auto" → "GitHub token"); I could not independently re-diff (the
   posterity-branch path didn't resolve in my probe), but the mitigations are pinned:
   the true original (31 560 B, blob `176816b` from `orchestrator-service@2bd6d06`) is
   staged at `/tmp/kilo/swarm-orchestration-service/swarm-run-20261026/orchestration_prompt.jinja2.md`
   and Stage 3 vendors THAT, byte-checked.
3. **Stage 2-parent worker dropped MCP `{env:…}` auth headers** — caught by the
   orchestrator's cold review, fixed in `ea8aea1`; env-var references are the
   committed pattern (`.secretscan-allow` covers them). Briefing lesson recorded.
4. **Both developments advanced mid-run** — verified (`5d990b0` parent, `5c88819`
   service). Stage 3's branch was cut pre-advance (`b12197f`) and would show the
   companion doc as deleted in its PR diff. Fix rule recorded: fetch immediately
   before every cut; merge `development` before push.

### B. Found in repo state / narrative by this analysis

5. **[HIGH] PR #13 stamps the wrong model pin.** The root `opencode.json` on
   `dev/rev2-stage2-v2-config-stamping` pins top-level `model:
   zai-coding-plan/glm-5.2` (verified via contents API) — the plan's O1 decision and
   Stage 2 Goal require **`zai-coding-plan/glm-5.3`**. Every clone stamped from this
   template would resolve the wrong model; the D4 canary would then guard the wrong
   pin. The worker carried the template's existing 5.2 pin instead of stamping O1's
   5.3; the cross-session memory even records "template's glm-5.2 pin kept" as a
   neutral fact, unrecognized as a defect; the debrief calls the PR merge-ready.
6. **[MED] Stage 1's done-when is unmet.** PR #12 is SKILL.md guidance only
   (+61 lines: chunked-apply rules, `Tee-Object` prescription, `$IssueNum` naming, a
   self-contained case-collision audit snippet — well-formed, and guidance is arguably
   the right mechanism since drivers are model-authored from SKILL.md, not
   templated files). But the stage's empirical clauses — a fresh tracking-init
   dispatch surviving on `ACP_IDLE_TIMEOUT=300`, and a delegation-quiet run surviving
   — never ran (they require a live dispatch, i.e. post-merge acceptance). "Completed,
   was verified" overstates; this is open acceptance work, not landed fact.
7. **[LOW] Debrief inaccuracy** — "budget used 5 of 50" vs `state.json` `spawned: 4`.
8. **[LOW] Uncommitted artifacts in the shared checkout** — the accurate findings
   bullet in `.agents/memory.md` and the untracked `docs/runs/` abort report both need
   a bookkeeping commit.
9. **[LOW] Stage 3 partial work is at risk** — uncommitted `+122/−49`
   (`prompt_builder.py`) on a `/tmp` worktree; `/tmp` is volatile across reboots.
10. **[INFO] #53 posterity untouched** — no pollution; reads only. (Retraction of the
    mid-run concern, recorded here deliberately.)
11. **[MED, DESIGN] The skill teaches a false scarcity: `maxSubagents` as a
    non-renewing lifetime budget.** Owner-corrected semantics (2026-10-26): total
    subagent spawns are NOT a limited count — the only real bound is on
    simultaneously-running workers. Yet the swarm skill states and *enforces* the
    opposite in six service-side surfaces plus the parent mirror: the run's
    "budget used 5 of 50" reporting is the contract working as written, not an agent
    error. Locations (all verified): `.agents/skills/swarm/SKILL.md` (description,
    inputs line 15, init, loop bullet, stop conditions, report line),
    `.agents/skills/swarm/scripts/swarm-state.ps1` (`-MaxSubagents` param, state
    field, `start-round` `BUDGET EXHAUSTED` hard stop),
    `.agents/skills/swarm/scripts/tests/SwarmState.Tests.ps1` (exhaustion tests),
    `.zcode/agents/swarm-orchestrator.md` + `.opencode/agents/swarm-orchestrator.md`
    (protocol steps 1 and 3), `.agents/skills/swarm-plan/SKILL.md:109` (init
    invocation), and word-for-word in swarm-context's `SKILL.md` + script + tests.
    Cost of the false model: orchestrators hoard spawns, report depleting budgets,
    and a productive run can be hard-stopped at 50 lifetime spawns for no real
    reason. Removing the stop also removes a runaway-cost brake — the remaining
    stops (3-fruitless-rounds stall guard, permission-parked workers, owner
    interrupt) still bound a runaway; owner accepts the trade-off.

## 3. Corrective actions

### 3.1 Fix the issues

- **F1 (from issue 5)** — Correct PR #13's pin: edit `opencode.json` on
  `dev/rev2-stage2-v2-config-stamping` (worktree `/tmp/kilo/swarm-context/wt/stage2-config`)
  to `"model": "zai-coding-plan/glm-5.3"`, commit, push, confirm checks re-green;
  correct the cross-session memory note.
- **F2 (issue 8)** — One bookkeeping commit to service `development`: the abort
  report + the memory bullet (the established `.agents/`-bookkeeping pattern).
- **F3 (issue 9)** — Commit the Stage 3 partial as a WIP commit on
  `dev/rev2-state-map` so it can't be lost.
- **F4 (issue 1)** — No pre-fix: the e2e free-port walk stays routed to the fresh
  run's Stage 2 service PR, per plan. (Memory + `-Port` workaround already de-risk
  local runs.)
- **F5 (issue 11)** — Replace the lifetime-budget contract with the true semantics:
  total spawns unlimited, bound only on concurrently-running workers.
  - `swarm-state.ps1`: rename `-MaxSubagents`/`maxSubagents` → `-MaxConcurrent`/
    `maxConcurrent` (default 50, now a concurrency ceiling); delete the
    `start-round` `BUDGET EXHAUSTED` stop; keep `spawned` as a cumulative,
    reporting-only counter.
  - Tests: exhaustion-stop tests replaced — `start-round` proceeds past any
    cumulative count; `maxConcurrent` recorded; coverage stays >85%.
  - `SKILL.md` (swarm): description drops "budget is exhausted"/"max-subagent
    budget"; inputs line becomes the concurrency ceiling with "total spawns are not
    limited"; loop bullet becomes a concurrency check; stop conditions lose
    `BUDGET EXHAUSTED`; report line reports cumulative spawns.
  - `swarm-plan/SKILL.md:109`: init invocation → `-MaxConcurrent <n>`.
  - `.zcode/agents/swarm-orchestrator.md` + `.opencode/agents/swarm-orchestrator.md`
    protocol steps 1/3: drop the budget stop and per-batch `spawned`-ceiling
    self-enforcement; state "keep simultaneous workers ≤ maxConcurrent".
  - Mirror word-for-word to swarm-context (`SKILL.md`, script, tests) as a parent PR.
  - Note (pre-existing drift, out of scope): parent's `.zcode`/`.opencode`
    orchestrator defs do not carry the budget lines the service copies do.

### 3.2 Reset state fresh for the next run

- **R1** — Rebase `dev/rev2-state-map` (now carrying its WIP commit) onto current
  `development` (`5c88819`) — unpushed branch, rebase is safe; keeps the future PR
  diff pure C with no phantom companion-doc deletion. Leave unpushed.
- **R2** — Stage 2-service worktree/branch (`dev/rev2-stage2-fallback-canary` @
  `5c88819`, clean) — keep as-is for the fresh run to reuse.
- **R3** — `.swarm/run-20261026-021751/` stays on disk as history (`stopped`); the
  fresh run initializes a new run id.
- **R4** — Parent PRs #12/#13 stay open, owner-gated. Recommended: apply F1, then
  review/merge #13; #12 needs owner judgment on guidance adequacy, with its live
  done-when as post-merge acceptance.
- **R5** — Fresh-run prompt amendments (drafted in §5): clauses 1–2 become
  "verify existing PRs" (they're already open); context gains the fetch-before-cut
  rule, the pin value named explicitly, the vendored-reference source, the MCP-env
  briefing note, the e2e-port memory pointer, and the branch/worktree reuse map.

## 4. Implementation plan (executed on approval, in order)

1. **F1** — parent worktree: fix the pin to `zai-coding-plan/glm-5.3`, commit
   (`fix: stamp the O1 model pin (glm-5.3), not the template default`), push, poll
   `gh pr checks 13` to green; fix the memory note's "glm-5.2 pin kept" line.
2. **F2** — service `development`: single commit adding `docs/runs/` abort report +
   this analysis + the memory bullet; push.
3. **F3 + R1** — Stage 3 worktree: WIP-commit the partial; rebase onto `development`;
   verify `git log` shows WIP atop `5c88819` with no companion-doc deletion in
   `git diff development...dev/rev2-state-map`; leave unpushed.
4. **F5** — concurrency-semantics fix: edit the six service-side surfaces (script,
   tests, swarm SKILL.md, swarm-plan SKILL.md, both orchestrator protocol bodies);
   run full `validation.ps1` (Pester rewrites must keep coverage >85%); open service
   PR to `development`; mirror to swarm-context and open the parent PR. Lands BEFORE
   the fresh run so the restart reads corrected semantics.
5. **R2** — re-confirm `wt/stage2-service` clean at `5c88819`.
6. **R5** — hand over the amended fresh-run prompt (goal + context) for firing in
   ZCode.
7. **Owner-side (listed, not executed):** review/merge #13 (post-F1) and #12; the D7
   org-hook check stays parked (clause 8); Stage 1's live done-when runs post-merge;
   review/merge the F5 service + parent PRs.

## 5. Fresh-run prompt (draft)

```text
/swarm goal: ALL true —
(1) parent PRs swarm-context#12 (Stage 1) and #13 (Stage 2 parent) verified: all
    present checks GREEN + MERGEABLE + zero unresolved threads, with #13's stamped
    opencode.json pinning zai-coding-plan/glm-5.3 (O1);
(2) Stage 2 service PR open (D4 canary + ACP_TRACE_ROOT rider + e2e free-port walk +
    strip-model-settings.ps1 root-layout update);
(3) Stage 3 PR open from dev/rev2-state-map (WIP commit present; rebased on
    development) with the §2 map, every §3 assertion passing, the vendored reference
    byte-identical to the staged original, and the orchestration: prefix dropped from
    the dispatch gate;
(4) each open PR: all present checks GREEN + MERGEABLE + zero unresolved threads;
(5) local validation.ps1 green with coverage >85% as of each stage's final run
    (e2e may run with -Port <free> per the 8765-squatter memory; CI is authoritative);
(6) Stage 3 acp_smoke probe shows a dispatched session quoting the map's contracts;
(7) D7, Stage 4, Stage 5 parked as documented blockers, not attempted;
(8) no PR merged by the swarm anywhere — all owner-merged.

context: plan doc = docs/plans/rev2-state-map-design.md — the implementation contract;
follow each stage's Goal/Context/Constraints/Done-when verbatim. Continuation state:
PRs #12/#13 already open (verify, don't recreate); Stage 3 continues from the WIP
commit on dev/rev2-state-map (worktree /tmp/kilo/swarm-orchestration-service/wt/
rev2-state-map); Stage 2-service worktree wt/stage2-service is clean at development —
reuse it. Rules: git fetch immediately before EVERY branch cut; MCP {env:…} auth
headers in stamped config are the committed pattern — never drop them; the vendored
reference comes from /tmp/kilo/swarm-orchestration-service/swarm-run-20261026/
orchestration_prompt.jinja2.md (orchestrator-service@2bd6d06, blob 176816b, 31560 B);
read .agents/memory.md Current Activity + the abort report in docs/runs/ before
decomposing.
```
