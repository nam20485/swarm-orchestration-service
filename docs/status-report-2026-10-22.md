# Three-Repo Status Report — 2026-10-22

Report date: 2026-10-22 (captured 2026-10-23 00:03 PDT).
Method: `.agents/memory.md` (this repo) cross-checked against **live** state — `git log`/branch topology
in all three local checkouts, `gh pr/issue/repo` reads on all three remotes, the running receiver
process (`/proc/<pid>/environ`), the trace root `logs/runs/`, `tailscale funnel status`, and the live
dispatch repo `nam20485/gap-miner-v2-kilo24`. Where memory and live state disagreed, live state won
(disagreements are called out below).

## Scope — the three projects

| Repo | Role | Live activity |
|---|---|---|
| `nam20485/swarm-orchestration-service` | **The service** — webhook listener → `PromptInfo` queue → ACP host; lifecycle owner (launcher, receiver, SwarmSandbox, `$swarm`) | Active daily; 1 open PR, 6 open issues, receiver deployed |
| `nam20485/swarm-context` | **Parent template / clone stamper** (`isTemplate: true`) — pruned to "agent-context base + swarm surfaces"; clones are stamped from it | Passive by design; 0 open PRs/issues; last merge 2026-10-19 |
| `intel-agency/agent-context` | **Grandparent / upstream base** — the stamper before the 2026-09-23 flip; upstream of the parent | Dormant since 2026-09-23; 0 open PRs/issues |

Template flow is one-way: **agent-context → swarm-context → this service** (syncs into the service are
reviewed PRs merging `upstream/development`); clones flow out of swarm-context only.

---

## The combined picture

### A. Chronology — all three repos, interleaved (oldest → newest)

`G` = agent-context (grandparent) · `P` = swarm-context (parent) · `S` = swarm-orchestration-service

```text
G                    P                         S
─────────────────────────────────────────────────────────────────────────────────────
2026-09-10   #24 dev→main merge ──bootstrap graft base (0d9c7dd)──▶  S forked (PR #1)
2026-09-12   G #25 MCP-cleanup ◀── word-for-word chain ──▶ P #5 ──▶ S 8a92019
             (the chain-wide-fix pattern: same change, reviewed PR in each repo)
2026-09-15   G #26 dev→main; query.ps1 reply-route fix authored (dev/query-reply-route)
2026-09-23   G #27+#28 query fix merged ──▶ P #6 same fix ──▶ S #22 same fix
             G goes dormant here ▲        P #7 template prune ◀── S-directed role split
                                           P #8 opencode roster port ◀── S mirrored
2026-10-14/15                              P #9 canary+pins+review sync ◀── S #31/#32/#33 rounds
                                                                        S webui W0–W2 merged #35–#37
2026-10-16/17                              P #10 worker thoughtLevel low ◀── S #38 v2 spawn fix
                                                                        S #40 worker pin · #41 v2 plan
                                                                        S epic #42 + stories #43–#47 cut
2026-10-17                                  FIRST UPSTREAM SYNC: S PR #49 merges P 02250c3 ▶ S
                                                                        S #48 webui fixes · probe PASS
                                                                        kilo24: first full hierarchy #2–31
2026-10-18                                                                        S #50 idle watchdog landed
                                           (nothing)                             S #49/#48/#51 MERGED; #51→main
                                             ▲ init-success marker fires run 0feb65c1
                                               (3.5 h, 633 calls, vague prose — the symptom)
2026-10-19                                  P #11 parity sync of #51 fixes — MERGED
                                                                                   forensic finding: Phase 3
                                                                                   ported away the rev2 clause
                                                                                   table (not a gate defect)
                                                                                   ▶ PR #53 rev2 restoration OPEN
2026-10-21/22                                                                      S #52 release train → main
                                                                                   (memory/docs only; code rode #51)
NOW                                         (nothing open)                      S PR #53 OPEN (CI green, 2 threads)
                                                                             receiver live: watchdog on, no ceiling
```

### B. Forward dependency stack — what unblocks what (top = first)

```text
① [S] Finish PR #53 "restore the mechanical rev2 clause-table prompt"
│      reply/fix the 2 Kilo SUGGESTION threads → run the merge-time acceptance
│      probe (clean e2e on a live clone) → owner-gated merge → deploy
│      ⚠ strip the stale ACP_PROMPT_TIMEOUT=3600 from .env BEFORE the restart
▼
② [S] First live mechanical loop on nam20485/gap-miner-v2-kilo24
│      Epic 1 → … → Epic 6, self-retriggering (init-success → implement-epic →
│      epic-implemented → next epic). Hierarchy #2–31 is primed, untouched.
│      This is the end-to-end validation of ①.
▼
③ [S] Epic #42 (opencode v2 config migration), stories in order:
│      #43 S1 stamp v2-shaped root opencode.json ──┐
│      │                                           ├──▶ ③a [P] parent template stamping surface
│      ▼                                           │      (+ launcher strip-model-settings.ps1)
│      #44 S2 credential strategy (env facade vs auth.json)
│      ▼
│      #45 S3 migrate/retire the v1-stamped clone fleet ──▶ ③b [fleet] gap-miner-v2-* clones
│      ▼
│      #46 S4 remainder (harness-trace S3 noise-filter fold-in; core watchdog DONE)
│      ▼
│      #47 S5 fresh-relabel e2e on a newly stamped v2 clone
│      (a freshly stamped clone can double as ①'s acceptance-probe target)
│
④ [S] /orchestrate-swarm skill implementation (skill-plan.md answered since 09-25, zero code)
│      ▼ first real ZCode swarm run — spawn gate cleared 10-17, never yet run
│      (independent of ①–③; parallel track)
│
⑤ [S→P] Next parity sync: NOTHING pending — #53 touches service-owned files only, and
│      P #11 made the shared surfaces both-sides-same, so the next S sync of P is
│      mechanical until shared surfaces (swarm defs / rules / skills) change again
│
⑥ [P→G] Grandparent graft: PARKED, trigger-gated (execute only when something is
       needed from agent-context; plan: docs/plans/grandparent-upstream-graft.md)
```

---

## 1. `swarm-orchestration-service` — the service (this repo)

### Recently completed (2026-10-14 → 10-22)

- **Release train #51 → #52 (merged).** PR #51 (merged 2026-10-18, `094f4e5`, admin bypass on owner
  directive) carried the whole October wave to `main`: the **web UI complete and live** (live SSE feed
  - runs history + webhooks views, JSONL export, coalescing, terminal-semantics rounds), the **idle
  watchdog** (#50 — kill only on inactivity, `ACP_IDLE_TIMEOUT` 300 s default; `ACP_PROMPT_TIMEOUT`
  repurposed as opt-in ceiling, default 0 = off), the **opencode v2 spawn fix** (#38 — argv rewritten
  for v2.0.31), the **first upstream sync** (#49 — parent `02250c3` merged; canary hardening `b920368`
  the only net delta), the **worker thoughtLevel fix** (#40 — GLM-5.3-Flash + `low`, parent mirror
  swarm-context#10), and the **v2-migration plan + epic** (#41; epic #42 with stories #43–#47). Three
  Kilo review rounds (18 + 1 + 1 threads) all fixed/replied/resolved; round-3 verdict "No Issues
  Found | Merge". PR #52 (merged 2026-10-21, `ce9686a`) was the follow-up train carrying only
  memory/doc commits — the code had already reached `main` with #51. `development` ⊆ `main` (0
  content commits ahead).
- **Parent-template parity sync swarm-context #11 (merged 2026-10-19).** Word-for-word mirror of the
  PR #51 review-round fixes to the shared surfaces (both swarm-analyst defs, king roster line,
  `swarm.md` `off`→`low`, the rules-metrics harness incl. the earlier service-side hardening the
  parent copy lacked). Deliberately not synced: `.gitignore` policy and service-only surfaces. Next
  sync will see both-sides-same-change on every touched file.
- **The init-success forensic finding (2026-10-19).** The `gh-issue-tracking:init-success`
  re-dispatch (kilo24 run `0feb65c1`, 3.5 h of vague-prose work) is **not a gate defect**: the gate
  is byte-identical to the frozen provenance; the marker has always been human-applied; what was lost
  is the old repo's *clause-table state machine* (init-success → find next unimplemented epic →
  `/orchestrate-dynamic-workflow implement-epic` → `epic-implemented`), which Phase 3 collapsed into
  one prose direction. Corroborated: the re-trigger was latent since the port and only became
  reachable with public ingress (2026-09-23) + a session that survived to stamp the marker.
- **Live-ops proof points.** Receiver deployed as a systemd user service and healthy; PAT `read:org`
  verified on the token (dispatched sessions can run `gh project` again); one-worker probe PASS
  (2026-10-17) — **the gate to the first ZCode swarm run is cleared**; first full tracking-init
  hierarchy created by a dispatched session (kilo24 issues #2–31, 2026-10-18).

### In flight (started, not finished)

- **PR #53 — "Restore the mechanical rev2 clause-table orchestration prompt"** (`dev/restore-rev2-clause-table`
  → `development`, opened 2026-10-19 16:22, MERGEABLE, all checks green: validate, droid-review, Kilo).
  The owner-directed reversal of the Phase 3 open-ended principle (*"i dont want it to be dynamic — i
  want it mechanical… the old system worked well and was proven through 2 working revisions"*):
  - Vendored byte-identical regression reference `src/webhook_receiver/orchestration_prompt.jinja2.md`
    (430 lines) from the frozen `orchestrator-service` @`2bd6d06`; `prompt_builder.py` rewritten
    (+613/−300) to deterministic Python clause **selection** (exact rev2-label match, first-match-wins)
    with near-verbatim clause **bodies**. The label cycle **is** the state machine:
    `direct-body` → `init-success` → (find next unimplemented epic → `implement-epic` with the epic
    **issue number**) → `epic-implemented` → review/report/debrief → close epic → **loop** until the
    plan is done. Rev1 `orchestration:*` labels fall to the `(default)` clause.
  - Pre-merge probe (2026-10-19) already paid off: it surfaced the `$epic` contract ambiguity, fixed
    as Decision 8 (commit `69f8983` — handoffs carry the epic issue **number**, not the title ordinal;
    `extract_epic_from_title` retired).
  - **Remaining before merge:** (a) the 2 open Kilo SUGGESTION threads — the `epic-implemented`
    clause's child→parent resolution step should name its lookup (e.g. GraphQL `parent { number }`)
    so the loop cannot stall, and the unused `REV2_LABELS` test constant should be iterated or
    dropped; (b) the merge-time acceptance step — a clean end-to-end probe against a **live** dispatch
    repo (the 10-19 probe went meta against the fake `owner/repo` target); (c) merge is owner-gated.
  - Plan doc: `docs/plans/restore-rev2-clause-table.md` (status IN PROGRESS, on the branch). The
    owner-checkout hazard it warned about (untracked copy of the vendored jinja2 file) is **cleared** —
    working tree is clean and the file is absent on `main`.

### Remains (not started / owner-gated / parked)

- **Epic #42 — opencode v2 config migration** (all stories OPEN): #43 S1 stamp v2-shaped root
  `opencode.json` from template + launcher (**touches the parent template** — strip-model-settings
  surface); #44 S2 credential strategy for dispatched sessions (env facade vs `auth.json`); #45 S3
  migrate or retire the existing v1-stamped clone fleet (`gap-miner-v2-*`); #46 S4 receiver knobs —
  core landed (#50/#51), remainder = harness-trace S3 noise-filter fold-in; #47 S5 verification —
  fresh relabel e2e on a newly stamped clone.
- **`/orchestrate-swarm` skill** — plan fully answered (skill-plan.md, 2026-09-25), zero code
  written. Follow-up from #53: the plan's taxonomy table cites Phase 3 label classes — stale after
  #53 merges; update when implemented.
- **First real ZCode swarm run** — unblocked since the 10-17 probe; never run.
- **Harness-trace plan remnants** — S3 noise filter, S4 golden `harness.log` rendering (event half
  subsumed by webui W0), S6 doc fixes; the plan header still says "S2–S6 unstarted" (stale).
- **Webui W3 exposure** (token auth + Caddy route) — owner-gated; current exposure is FINAL =
  loopback + SSH tunnel only.
- **Live-ops hazard (found by this report):** `.env` again contains `ACP_PROMPT_TIMEOUT=3600`
  (retired 2026-10-18; re-accumulated after the 2026-10-20 10:37 unit restart). The **running**
  process was verified clean (`/proc/2330/environ`: only `ACP_ENABLED=true` +
  `ACP_CLONE_ROOT=/home/nam20485/src/github/nam20485/dynamic_workflows`) — ceiling currently off,
  watchdog on the 300 s default — but the stale line **binds as the 60-min hard ceiling on the next
  unit restart**. Strip it before restarting (e.g. when deploying #53).
- **Remember-To-Do ledger:** python tests pollute `logs/runs/` with placeholder-owner/repo traces
  (pin `ACP_TRACE_ROOT` to `tmp_path`); `swarm-state.ps1` concurrent-not-all-time budget semantics;
  per-run telemetry archiving to `.swarm/<run-id>/telemetry/`; SwarmSandbox AppHost never gated
  (manual `dotnet run` smoke when next needed); Projects v2 board rule lapsed (token blocker gone —
  reviving is an owner call).
- **Owner-gated / parked ledger:** old-stack decommission (plan-only); grandparent graft (parked,
  trigger-gated); turing-alpha bot account (proposed); `workflow-launch2` teardown + label-file
  reconciliation; `GITHUB_TOKEN` consolidation (deferred); `GEMINI_API_KEY` rotation; issue-dependency
  webhook events as a future trigger.

### Next (in dependency order)

1. Close out PR #53: answer the 2 threads → acceptance probe on a live clone (kilo24, or a freshly
   stamped one) → owner-gated merge → strip the stale `.env` 3600 line → restart + deploy.
2. Watch the first live mechanical loop on kilo24 (Epic 1 → Epic 6, no human re-fire between epics).
3. Epic #42 starting at #43 (S1) — coordinate the parent-template stamping surface change.
4. Implement the `/orchestrate-swarm` skill → first real swarm run (parallel track).
5. Fold housekeeping into the next PR: trace-pollution test fix, harness-trace header, webui-plan
   archive to `completed/`, stale local branch deletes.

---

## 2. `swarm-context` — parent template / clone stamper

### Recently completed

- **PR #11 (merged 2026-10-19)** — parity sync of the service PR #51 review-round fixes to the shared
  swarm surfaces (the last open item from the service's October wave; the flagged follow-up the owner
  approved with "//do it").
- **PR #10 (merged 2026-10-17)** — worker `thoughtLevel: low` mirror (the fix that unblocked swarm
  spawns service-side).
- Earlier: #9 canary-harness + model-pins + review-fix sync (10-15), #8 opencode roster port (09-23),
  #7 template prune to the parent role (09-23).

### In flight

- **Nothing.** Zero open PRs, zero open issues. The parent's local checkout is clean but **stale**:
  on `development` @`02250c3` while origin/development has moved (#11 merge + two memory commits) —
  a `git pull` whenever work resumes there.

### Remains

- No self-directed work. The parent changes only when (a) the service lands shared-surface changes
  (swarm defs, `.agents/rules/swarm*.md`, shared scripts) that mirror out word-for-word, or (b) a
  clone-stamping surface must change — the next known case is **service epic story #43 (S1)**: v2-shaped
  root `opencode.json` stamping, which will require parent template + `strip-model-settings.ps1`
  work (dependency ③a in the stack above).
- Housekeeping: `dev/swarm-plan-wizard` branch (local + remote) is stale — **0 commits ahead of
  `development`** (the swarm-plan skill it incubated is committed); safe to delete on both sides,
  owner-gated per branch-hygiene rules.

### Next

- Standby for the #43 (S1) stamping-surface coordination; otherwise only routine syncs.

---

## 3. `intel-agency/agent-context` — grandparent / upstream base

### Recently completed

- **Last real activity: 2026-09-23** — the query.ps1 reply-route fix (#27) and the dev→main sync
  (#28), the tail of the three-way chain fix (G #27 → P #6 → S #22). Before that: the MCP-cleanup
  chain (#25, 09-12) and the rules/docs wave (#23/#24, 09-10).
- **Blacksmith runner PR #18 — RESOLVED (was parked).** The owner closed it unmerged on 2026-09-14;
  live read confirms CLOSED. Recommendation on record stands for the future: if Blacksmith is ever
  adopted, leaf repo first, never the template origin. (This closes a parked item the service memory
  still lists as deliberating.)

### In flight

- **Nothing.** Zero open PRs/issues; working tree clean. Dormant upstream base.

### Remains

- **Grandparent graft — PARKED, trigger-gated** (plan: `docs/plans/grandparent-upstream-graft.md` in
  the service). The parent is a squashed seed whose root is not in the grandparent's history; the
  first true G→P sync needs graft surgery that cascades to the service. Execute only when something
  is needed from the grandparent. Nothing currently is.
- Chain-wide script fixes (the query.ps1 pattern) still route through it when shared scripts change —
  none pending.
- Housekeeping (cosmetic): the local checkout sits on the long-merged topic branch
  `dev/query-reply-route` (switch back to `development` on next use); a dozen stale local branches
  (`traycer/*`, `dev/*`, `mn/*`) from the pre-split era.

### Next

- None self-directed. Re-enters the picture only via ⑥ (graft, parked) or a chain-wide fix.

---

## Cross-repo sync obligations (standing rules, current state)

| Obligation | Direction | State |
|---|---|---|
| Shared-surface parity (swarm defs, swarm rules, shared scripts) | S → P, word-for-word, reviewed PR | Current (P #11, 10-19); nothing pending from #53 (service-owned files only) |
| Template sync (upstream merge) | P → S, reviewed PR | Current (S #49, 10-17, base `02250c3`); next sync mechanical — P's only newer commits are #11's both-sides-same content |
| Clone stamping | P → new repos (`gap-miner-v2-*`, and `Odbdesign-info-client-india79-b` stamped 2026-10-22) | Active; the fleet is alive |
| Chain-wide script fixes | G → P → S | Current (query fix, 09-22/23); none pending |
| Grandparent graft | G → P | PARKED, trigger-gated |

## Ops snapshot (service, at capture time)

- Receiver: systemd user unit **active since 2026-10-20 10:37 PDT**, `/health` 200.
- Ingress: `tailscale funnel` **on** (`precision5820.tail11ba79.ts.net` → 127.0.0.1:80 → Caddy →
  receiver :8080) — the webhook path is healthy.
- Effective dispatch config (verified on the running process): clone-mode dispatch on
  (`ACP_ENABLED=true`, `ACP_CLONE_ROOT=…/dynamic_workflows`), **no** prompt ceiling, idle watchdog at
  the 300 s default. Deployed code = `development`@`dc8db7d`-era == `main` content; **PR #53 is not
  deployed**.
- Traffic: no dispatch runs since 2026-10-19 00:20 (last FIFO runs after the init-success marker);
  webhook deliveries are still arriving (global `events.jsonl` tail written 2026-10-23 00:02).
- Primed target: `nam20485/gap-miner-v2-kilo24` — Plan #2 + Epic 6 + stories all OPEN, no
  implementation labels: ready to exercise PR #53's mechanical loop.
