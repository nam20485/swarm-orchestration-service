# charlie68 Incident Follow-ups — Decision Items for Implementation

Status: **DECIDED 2026-10-24 — all items resolved (D1 a+b, D2 → migration S1 with
`zai-coding-plan/glm-5.3`, D3 recommendation, D4 canary, D5 partial-done, D6
autonomous cycle with 3-round budget + green/zero-threads merge) — ready for
implementation**
Audience: any dev agent (Kilo/opencode) tasked with implementation
Incident window: 2026-10-23 08:50–17:06 UTC (runs `b3dfddf8` → `7ad18141`)
Full narrative: `.agents/memory.md`, project bullet "opencode v2.1.3 default-model
regression diagnosed + pinned (2026-10-23…)". This doc carries the decisions and
the D2 research record.

## Verified current state (2026-10-24)

- `intel-agency/gap-miner-v2-charlie68`: Plan #2 + Epics #3–9 + Stories #10–31,
  all labeled/milestoned/board-linked; `gh-issue-tracking:init-success` on Plan #2.
  Story 1.1 (#10) implemented, labeled `implementation:complete` + `needs-review`.
  **PR charlie68#32 (`dev/story-1-1-repo-bootstrap`) still OPEN** — first target of
  the D6 autonomous cycle once it exists. (swarm-orchestration-service#32, merged
  2026-10-15, is unrelated.)
- Clone repos have **no branch protection** (verified: empty rules, protection
  disabled on charlie68 `development`) — a dispatched session can merge its own
  PR once checks are green. The REVIEW_REQUIRED bypass problem is specific to
  THIS repo.
- Model pin in force (interim, host-global): `"model": "zai-coding-plan/glm-5.3"`
  in `~/.config/opencode/opencode.json` (backup `opencode.json.bak-20261023`).
- `.env:154`: `ACP_IDLE_TIMEOUT=900` commented out by owner. The running unit
  (restarted 2026-10-23 19:03 PDT with 900s) still enforces 900s until the next
  restart — which re-arms the 300s default and D1's kill mode.
- Incident record committed + pushed 2026-10-24 (`c1a2e06` memory+rules,
  `5ff8461` this doc v1). Foreign artifacts still uncommitted: `.gitignore`
  (+`.pair/`), `*.code-workspace` (dotrush), `.qoder/`,
  `docs/status-report-2026-10-22.md` (its MD004 lint error fixed in-tree to
  unblock the gate; still untracked).

## D1 — Long-silent-apply survival (watchdog false positive) — FIRST

**Problem.** `gh-issue-tracking-init`'s board/milestone apply runs as ONE bash
call with output redirected (`pwsh … > apply-runN.log 2>&1`), so during a
>300s apply neither liveness signal the idle watchdog uses (session updates,
stderr lines — PR #50) fires, and the watchdog kills a live run. Observed live
(run `df4c8f2d`, killed at 302s mid-board-onboarding).

**Decision (owner 2026-10-24): (a) + (b).** Driver emits liveness (stop
redirecting stderr — progress then feeds the PR #50 signal) AND chunked apply
(split board onboarding per-epic, ~7 calls of ~40s). Both land in the parent
template. With the 300s default re-armed at the next receiver restart, this is
the primary mitigation — until it lands, any tracking-init dispatch risks the
mid-apply kill (recoverable by idempotent re-dispatch).

**Done when.** A fresh tracking-init dispatch completes board onboarding with
`ACP_IDLE_TIMEOUT=300` in effect, end to end, watchdog never firing.

## D2 — Model selection for dispatched clones — RESOLVED BY RESEARCH → implement migration S1

**Owner direction (2026-10-24):** models are set by the service, not client/ACP
or host-user config; the parent template must KEEP its pins (it seeds
non-orchestrator clones too); recollection that the seeder is the right place.

**Research findings (all first-hand, 2026-10-24):**

1. `scripts/strip-model-settings.ps1` header (imported verbatim in `ddc6037`):
   the original design is **service-owned model selection via the dispatch
   `--model qwencloud/qwen3.7-max --variant high`** on the old stack. The
   template keeps pins for interactive/non-orchestrator use; the strip REMOVES
   (not rewrites) clone pins "so every layer falls back to the
   orchestrator-service dispatch/runtime settings."
2. The port dropped that fallback layer: `opencode acp` takes **no model flag**
   (`--help`: only `--login`), and the Phase-2 port deliberately carried none
   (Decision 10, zero host-side pins). So the layer the strip contract falls
   back to does not exist — post-strip sessions resolve opencode's
   version-dependent default (v2.0.31: authenticated zai GLM, worked;
   v2.1.3: authless `flint-40b-free`, intermittently rejects requests).
3. The already-approved plan owns the fix:
   [`opencode-v2-config-migration.md`](opencode-v2-config-migration.md)
   (PLAN — owner-approved direction 2026-10-16; epic #42 + stories #43–47):
   - **Finding 1**: v2 no longer reads `.opencode/opencode.jsonc` at all —
     project config is a **root `opencode.json`**. The launcher-stamped clone
     config (providers, `default_agent`, permissions, MCP) is silently dead in
     v2; dispatch sessions have been running on host-global config + catalog
     fallback only.
   - **S1 (unimplemented — verified: no root `opencode.json` in parent template
     or charlie68)**: template + launcher stamp a v2-shaped root `opencode.json`
     with `default_agent`, **`model` pin**, provider blocks (baseURL only, no
     secrets), MCP servers; `strip-model-settings.ps1` updated for the new
     layout. *Done when*: a fresh clone's `opencode debug config` shows the root
     doc loaded and a hand-run session picks the pinned model.
   - S2 credential strategy, S3 existing-clone fleet follow.

**Resolution: implement S1** — this IS the owner's remembered "set during the
seeder script" design, already approved as direction. The stamped pin makes the
service the model owner at the project-config layer (highest persistent
precedence below per-session overrides). The host-global pin stays as interim
until S1 lands, then is removed. **Open question O1** (pin value) below.

## D3 — Case-insensitivity guard in the tracking-init skill

**Decision (owner 2026-10-24): take recommendation** — (a) add the guard +
symptom signature to `gh-issue-tracking-init` in the parent template AND (b)
fix the shipped driver templates to use distinct names (`$IssueNum`), in the
same parent PR as D1(a)/(b).

**Done when.** Parent PR merged; next seeded clone contains the guard; a fresh
tracking-init run generates case-clean drivers (spot-check `parts/*.ps1`).

## D4 — opencode binary version control

**Decision (owner 2026-10-24): (c)** — canary first, pin optional. Implement a
spawn-time/boot-time canary that fails loudly (or warns) when the harness
resolves a fallback/free-tier model or fails a handshake probe — it would have
caught both auto-update regressions (2026-10-16 argv, 2026-10-23 fallback) at
zero workflow cost. Side-by-side pinned binary via `ACP_OPENCODE_BIN` remains a
later option.

**Done when.** The receiver logs a clear warning/error on fallback-model
resolution; a test pins the canary behavior.

## D5 — Commit hygiene — PARTIALLY DONE

Incident record committed and pushed (`c1a2e06`, `5ff8461`). Foreign artifacts
remain for the owner: `.gitignore` (+`.pair/`), dotrush workspace settings,
`.qoder/` (gitignore it if the tool stays), `docs/status-report-2026-10-22.md`.

## D6 — Autonomous PR cycle (no human gate between stories) — NEW WORKFLOW

**Owner direction (2026-10-24):** the pipeline must not stop after every epic
implementation waiting for human PR approval. The next-step direction should
invoke an agent-instructions workflow / dynamic workflow: orchestrator
delegates review to subagents (auto-review), then `/resolve-pr-comments`, then
`/fix-failing-workflows`, iterating until GREEN/MERGEABLE, then **merge**, then
advance to the next story (or next epic when the epic's last story closes).

**Design context.** This un-defers the old stack's post-merge chain
(`epic-implemented → review-epic-prs → report-progress → debrief-and-document`),
explicitly marked deferred at the Phase-3 port (memory 2026-10-19). It is NEW
prompt/direction work — a new per-label direction in `prompt_builder.py` (or a
dynamic workflow the direction invokes). Verified enabler: clone repos carry no
branch protection, so session-driven merge needs no bypass. Mechanism options
(security posture): full `mode: primary` merge authority vs merge via the same
PAT the session already holds.

**Done when.** After a story-implementation PR is opened, the pipeline drives
review → fix → green → merge → next-story dispatch with no human step; failure
after budget parks the PR with a label and moves on (or stops — O2).

## Resolved questions (owner, 2026-10-24)

- **O1 — S1 pin value: `zai-coding-plan/glm-5.3`** (proven; coding-plan auth
  already on the host). The seeder stamps this into clones' root
  `opencode.json`.
- **O2 — D6 review-loop budget: 3 auto-review/fix rounds**, then park the PR
  with `needs-owner` and advance to the next story.
- **O3 — D6 merge gate: CI green + zero unresolved review threads** (machine
  gate; no additional verdict required).

## Suggested implementation order (updated)

1. ~~D5 incident record~~ — done (`c1a2e06`, `5ff8461`)
2. **D1 + D3** — one parent-template PR (driver liveness + chunked apply +
   case guard) — before heavy dispatches resume (300s rearms at next restart)
3. **D2** — implement migration **S1** (answers O1 first) + D4 canary — one
   service-side PR; drop the host-global pin when S1 is verified
4. **D6** — autonomous PR-cycle direction (answers O2/O3) — service PR; then
   charlie68#32 becomes its first live exercise instead of a human gate
