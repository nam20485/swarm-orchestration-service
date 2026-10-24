# charlie68 Incident Follow-ups — Decision Items for Implementation

Status: **PROPOSED — awaiting owner go/no-go per item; D1 is sequence-blocking**
Audience: any dev agent (Kilo/opencode) tasked with implementation
Incident window: 2026-10-23 08:50–17:06 UTC (runs `b3dfddf8` → `7ad18141`)
Full narrative: `.agents/memory.md`, project bullet "opencode v2.1.3 default-model
regression diagnosed + pinned (2026-10-23…)". This doc only carries the decisions.

## Verified current state (2026-10-24 ~10:14 UTC)

- `intel-agency/gap-miner-v2-charlie68`: Plan #2 + Epics #3–9 + Stories #10–31,
  all labeled/milestoned/board-linked; `gh-issue-tracking:init-success` on Plan #2.
  Story 1.1 (#10) implemented, labeled `implementation:complete` + `needs-review`.
  **PR charlie68#32 (`dev/story-1-1-repo-bootstrap`) still OPEN — the pipeline's
  human gate.** (Do not confuse with swarm-orchestration-service#32, merged
  2026-10-15, unrelated.)
- No dispatch runs since 17:06 UTC 2026-10-23.
- Model pin in force: `"model": "zai-coding-plan/glm-5.3"` in
  `~/.config/opencode/opencode.json` (backup `opencode.json.bak-20261023`).
- `.env:154`: `ACP_IDLE_TIMEOUT=900` commented out by owner (2026-10-24).
  The receiver process last restarted 2026-10-23 19:03 PDT **with** the 900s
  value, so the running unit still enforces 900s; **the next restart reverts to
  the 300s default and re-arms D1's kill mode**.
- Uncommitted in this repo: `.agents/memory.md` (incident bullet) and
  `.agents/rules/validation.md` (gotcha #3) — incident artifacts, ready to
  commit; `.gitignore` (+`.pair/`), `*.code-workspace` (dotrush settings),
  `?? .qoder/`, `?? docs/status-report-2026-10-22.md` — foreign/parallel-session
  artifacts, owner to commit/ignore/discard.

## D1 — Long-silent-apply survival (watchdog false positive) — BLOCKING FIRST

**Problem.** `gh-issue-tracking-init`'s board/milestone apply runs as ONE bash
call with output redirected (`pwsh … > apply-runN.log 2>&1`), so during a
>300s apply there are no session updates and no stderr lines — both liveness
signals the idle watchdog uses (PR #50) are starved, and the watchdog kills a
live run. Observed live 2026-10-23 (run `df4c8f2d`, killed at 302s; apply log
ends mid-board-onboarding). With the owner's revert to the 300s default, the
next tracking-init dispatch on any clone will very likely die mid-apply again
(recoverable only by idempotent re-dispatch, ~15 min + tokens each time).

**Options.**
- (a) **Driver emits liveness**: stop redirecting stderr in the apply invocation
  (progress lines then feed the existing PR #50 stderr signal). Smallest change,
  but lives in the *skill/template* (parent PR, parity rule) — see D3 vehicle.
- (b) **Chunked apply**: split board onboarding per-epic (7 calls of ~40s)
  instead of one monolith. Most robust; more driver surgery.
- (c) **Raise `ACP_IDLE_TIMEOUT` again** (receiver-only, no template change) —
  treats the symptom; owner just declined this as the standing answer.

**Recommendation.** (a) + (b) combined in one template PR; until it lands, do
not lower the runtime below 900s (or accept re-dispatch costs).

**Done when.** A fresh tracking-init dispatch completes board onboarding with
`ACP_IDLE_TIMEOUT=300` in effect, end to end, watchdog never firing; e2e
assertion added to the receiver's simulator (`scripts/e2e-orchestration.ps1`)
or template tests where the driver lives.

**Decision:** A+B as reco'd

## D2 — Where the dispatch model pin lives (governance)

**Problem.** The Oct 23 deaths happened because dispatch sessions resolved no
model anywhere: host code carries none (Decision 10), clones have pins stripped
by `strip-model-settings.ps1` (by design, predates the PR #40 pins), and the
host global config had none. opencode's fallback default is
version-dependent (v2.1.3 flipped it to the authless `flint-40b-free` free
tier, which rejects requests intermittently — `Endpoint is unavailable` — and
one rejection kills the session). Today's emergency pin is host-global and
documented only in memory.

**Options.**
- (a) **Keep host-global pin + document it** in `.agents/rules/` (ops surface)
  and the deploy checklist. Simplest; also restores interactive-session
  semantics to pre-2.1.3; but host-global scope is broader than the service.
- (b) **Receiver-scoped pin**: verify (against opencode docs — do not derive
  config syntax) whether an env var can set the model for ACP sessions; if yes,
  carry it in the receiver env (`.env` + `.env.example`), the governed surface.
- (c) **Seeder writes the pin into clones** (un-strip or rewrite to a
  host-provided value) — reaches every clone but changes the strip-by-design
  decision and the parity rule surface.

**Recommendation.** (b) if the env var exists, else (a) with documentation;
(c) only if clones are ever dispatched from machines with different providers.

**Done when.** The pin is explicit, documented, survives receiver
reinstalls/machine rebuilds, and a startup check asserts the resolved session
model is the pinned one (not a fallback) — cheap canary: `acp_smoke`-style
probe or a boot-time config assertion.

**Decision:** We've alrady been over this. Models are set by the service, not in the cvlient or ACP. And def. not on the user-wide host-machine level. So it needs to be inthe parent template- no, no- see we've done this already. We had to leave the parent template pinned bc its used to seed other templatge clones than just swartm-orchestraiton-service clone app seedlings. So i think we decided it needed to be set during the seeder script. I can't remember the nuances now- it was compliacted. I dont know what happened- we've done a lot of work here in the rtecent past. Do some research and see if oyu can find the evidence and any decisions or implemtnaitons. Report back.

## D3 — Case-insensitivity guard in the tracking-init skill (parent template)

**Problem.** The Oct 23 session's model-authored driver died on
`$Num`/`$num` — the same variable in PowerShell (case-insensitive); the capture
clobbered the hashtable. Guarded service-side in
`.agents/rules/validation.md` gotcha #3, but that file is service-owned and
does not propagate. Dispatch sessions read the *clone's* skill.

**Options.** (a) Add the guard + symptom signature to
`.agents/skills/gh-issue-tracking-init/` in the **parent template**
(swarm-context) — one reviewed PR per the parity/lifecycle rules; clones stamp
it. (b) Also fix the skill's shipped driver templates to use distinct names
(`$IssueNum`) so generated code inherits safety.

**Recommendation.** (a) + (b) in the same parent PR that carries D1(a)/(b).

**Decision:** take reccomendaiton

**Done when.** Parent PR merged; next seeded clone contains the guard; a fresh
tracking-init run generates case-clean drivers (spot-check `parts/*.ps1`).

## D4 — opencode binary version control

**Problem.** Both regressions in the incident record arrived silently via
auto-update (v1.18→v2.0 argv break on 2026-10-16; v2.0.31→v2.1.3 model-fallback
flip on 2026-10-23). The ACP SDK is pinned (`agent-client-protocol==0.12.1`);
the binary floats.

**Options.** (a) Side-by-side pinned install + `ACP_OPENCODE_BIN` (receiver
env) — deterministic; requires an update policy (security fixes?). (b) Accept
auto-update, add a boot-time/session-start canary asserting the resolved model
and a minimal handshake (overlaps D2's canary). (c) Both: pin + canary.

**Recommendation.** (c), starting with the canary (it would have caught both
incidents at spawn time, zero workflow change).

**Done when.** The receiver fails loudly (or logs a clear warning) when the
harness resolves a fallback/free-tier model or fails a handshake probe.

**Decision:** c, take recomenadtion.

## D5 — Commit hygiene for the incident artifacts

- `.agents/memory.md` + `.agents/rules/validation.md`: incident record — run
  `/safe-commit` and commit (rules: validation gate first).
- `.gitignore` (+`.pair/`), `*.code-workspace` dotrush block, `.qoder/`,
  `docs/status-report-2026-10-22.md`: not authored by the incident session —
  owner decides; `.qoder/` likely wants a gitignore entry if the tool stays.

**Decision:** sounds good

## D6 — charlie68 pipeline continuation (owner gate)

Review/merge **charlie68#32** (Story 1.1). The post-merge labels
(`epic-implemented` / next `implementation:ready`) re-drive the cycle. Sequence
note: land D1 (or keep the 900s runtime) before heavy further dispatches,
because the next receiver restart re-arms the 300s watchdog against the
long-apply pattern.

**Decision:** OK but this is an autonmous workflow, it cant stop inafter every epic implemenation and wait for the human to approve a PR and merge it. The next _DIRECTION or whtever should be to invoke an agent-ionstructrions workflow or dynamic workflow to have the orchestrator invoke auto reviews or delegate to  subagents review the PR, then `/resolve-pr-comments`, then `/fix-failing-workflows`, until it GREEN?MERGABLE and then merge it. Then on to the next epic story (or epic, if the last cycle closed out the epic by implementing/reviewing jthe epic's last story.

## Suggested implementation order

1. D5 (commit incident record) — unblocks clean branches
2. D1 + D3 — one parent-template PR (driver liveness + chunking + guard)
3. D2 + D4 — one service-side PR (pin governance + canary)
4. D6 — owner merges charlie68#32; pipeline resumes on the fixed surfaces