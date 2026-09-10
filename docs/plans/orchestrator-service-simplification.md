# Orchestrator-Service Simplification — Analysis & Plan

Status: APPROVED (owner decisions folded 2026-09-10 — see §5; ready for Phase 0)
Date: 2026-09-10
Requirements source: [`docs/plans/orchestrator-service-integration.md`](./orchestrator-service-integration.md) (owner's direction notes)
Codebase surveyed (reference only): `nam20485/orchestrator-service` @ branch `nam20485`, HEAD `2bd6d06` (2026-09-10; working tree there has 38 modified + 2 untracked files — the old repo stays untouched per Decision 8; port listener/webhook code from it, do not build in it)

## 1. Executive summary

Replace the bespoke opencode-attached dispatch and the prompt-encoded rigid state machine of the
old `orchestrator-service` with: a **strongly typed async `PromptInfo` queue** (net-new — it does not
exist today) feeding an **ACP host** that drives agent CLIs (opencode first) through the Agent
Client Protocol instead of an always-on `opencode serve` container. The GitHub side (App webhook,
HMAC verify, label-filtered dispatch) stays as-is. The rigid "match-clause" workflow cycle is
replaced by an open-ended agent orchestration prompt, per the owner's direction: the models can
handle dev workflows end-to-end now. Two entry paths must exist: **new app** (plan →
`gh-issue-tracking-init` → swarm) and **new feature / existing app** (plan → Epic/Story/Task
issues in the existing tracking → swarm). The interactive planning wizard frontend has already
landed in this repo as `/swarm plan` (`.agents/skills/swarm-plan/`). **Implementation lands in a
new repo — `nam20485/swarm-orchestration-service`, cloned from this template and linked
fork-style (Decision 8) — carrying both sides: the orchestration service and the swarm driver,
with SwarmSandbox provisioning the execution environment (Decision 5).**

## 2. What exists today (evidence)

| Component | Where | How it works |
|---|---|---|
| Webhook listener | `webhook_receiver/app.py` (FastAPI, :226 `github_webhook`) | HMAC `X-Hub-Signature-256` verify (`github.py`, secret `OS_WEBHOOK_SECRET`) → `should_dispatch` gate (`filters.py:97`: only `issues.labeled` by a non-bot sender with a workflow label; namespaces `orchestration:*`, `gh-issue-tracking:*`, exact `implementation:ready/complete`) → prompt build → FastAPI `BackgroundTasks` → `subprocess.Popen` |
| Orchestration "state pattern" | `webhook_receiver/orchestration_prompt.jinja2.md` (431 L) | **Pure prompt text**: EVENT_DATA first-match-wins match clauses (lines 123–408) executed by the LLM; each clause applies the *next label*, whose webhook re-triggers dispatch (plan-approved → create-epic-v2 → epic-ready → implement-epic → epic-implemented → review-epic-prs → epic-reviewed → report/debrief → epic-complete → next epic). No code state machine exists. |
| Workflow step bodies | external repo `nam20485/agent-instructions` | fetched fresh at runtime; in-repo command is a pointer |
| opencode integration | `runner.py:722 dispatch_to_opencode` → `scripts/prompt.ps1` → `opencode run --attach http://…:4099` | **Always-on** `opencode serve` container (compose `orchestratorservice`, :4099) + one-shot `opencode run` per dispatch; defaults model `qwencloud/qwen3.7-max`, agent `orchestrator`, variant `high`; fail-closed permission block (no `--auto`); watchdog kills permission asks after 60 s |
| Eventing | `event_store.py:58 EventStore` | untyped `deque` + per-subscriber `queue.Queue` → dashboard SSE only. **`PromptInfo` does not exist** (grep-verified) — no Redis, no asyncio.Queue; webhook→agent handoff is BackgroundTasks+Popen |
| Second engine | `beads_loop.py BeadsLoop` (thread) | independent Beads pipeline (plan→DAG→per-bead worktrees→PRs) sharing only `_prompt_script_invocation` + workspace layout; documented as additive/coexisting |
| Interactive wizard | `image/.opencode/skills/plan-app/SKILL.md` (+ template) | 7-gate linear wizard → `plan_docs/application_plan.md` (canonical path, feeds `_plan_tracked()` and per-bead worktrees) — **ported to swarm-context as `swarm-plan`** |
| Notifications back to GH | `runner.py:426 _post_issue_comment` etc. via `gh` CLI | PAT `GH_ORCHESTRATION_AGENT_TOKEN` (no App installation-token minting) |
| Deployment | `compose.yaml` (3 services) + Caddy proxy | `orchestratorservice` (opencode serve), `webhook-receiver` (Python), `webhook-proxy` (Caddy, `/webhooks/github` + `/health` only) |

Known gap stated in-repo (`image/.opencode/AGENTS.md:41`): nothing currently drives implementation
after `/gh-issue-tracking-init` builds the hierarchy — exactly the gap the swarm integration closes.

## 3. Target architecture

```text
GH App webhook ──► webhook listener (FastAPI, unchanged contract)
                      │ constructs PromptInfo
                      ▼
              PromptInfo async queue (net-new, strongly typed)
                      │ consumer
                      ▼
              ACP host (replaces orchestrator-service dispatch + opencode-serve container)
                ├─ agent-orchestration prompt (open-ended pseudo-code workflow,
                │   replaces the jinja2 match-clause cycle)
                ├─ ACP client registry (opencode first; kilo/qwen/zcode later)
                └─ paths: (a) new app → plan → gh-issue-tracking-init → swarm
                          (b) new feature/existing app → plan → existing tracking → swarm
```

Keep (unchanged): GitHub App + webhook + HMAC; the Python FastAPI listener; the label namespaces
and dispatch gate; Caddy proxy; PAT-based `gh` notifications; the dashboard/SSE store (fed with
new event types). The `orchestratorservice` always-on `opencode serve` container is **deleted** —
the host prompts the CLI over ACP directly.

### 3.1 PromptInfo queue (net-new)

The requirements say "keep", but nothing exists to keep — the only queue-ish thing is the untyped
SSE `EventStore`. Design decisions needed (see open questions): typed dataclass/pydantic model
(id, source, repo, event payload, prompt, priority, enqueue/dedup key, status); backing store
(in-process `asyncio.Queue` vs Redis streams vs sqlite WAL) given the single-listener deployment;
durability/retry semantics for missed dispatches; and whether `EventStore` merges into it or stays
a separate dashboard concern.

### 3.2 ACP host

One process (likely the webhook-receiver itself, or a sibling container) that speaks the Agent
Client Protocol as **host**: launches a configured agent CLI (`opencode` first) as an ACP agent
per prompt (or reuses a warm session), feeds the orchestration prompt + PromptInfo payload,
streams progress to the dashboard, and collects the result. Client selection is config-driven
(“any pre-configured ACP client”): opencode on this host today; kilo code CLI / qwen code / zcode
when they ship ACP agent support.

*(ACP protocol specifics, launch commands, and per-client readiness: see §6.)*

### 3.3 Agent orchestration prompt

Replace `orchestration_prompt.jinja2.md`'s rigid clause table with an open-ended prompt carrying
the workflow as pseudo-code / natural language (the owner's direction), e.g.:

```text
on PromptInfo p:
  if p is new-app:      plan (swarm-plan wizard or autonomous variant) → gh-issue-tracking-init → swarm
  elif p is feature:    plan against existing tracking → swarm
  else:                 run the named workflow from agent-instructions
  publish & verify (branch, PR, labels) as the in-repo workflows already specify
```

Clauses no longer encode "which label applies next" — the agent decides from the tracking state
(issues/labels queried via `gh`), which also removes the webhook-echo state cycle as the only
progression mechanism. GitHub-side notifications stay (comments, labels, PRs).

**Reuse from this repo** (owner direction, 2026-09-10): the majority of the swarm-plan
implementation is co-optable for the host's plan-app avenue — the wizard steps, the
`plan_docs/application_plan.md` output contract (which `gh-issue-tracking-init` already
consumes), and the goal-derivation gate become the planning prompt the ACP agent runs for
paths (a)/(b); an autonomous variant of the wizard (defaults chosen instead of asked) feeds
directly off PromptInfo payloads, keeping the interactive form for human-initiated runs.
Decision 8 makes this concrete: the orchestration repo is a clone of this template, so the
swarm assets ship with it.

## 4. Gap analysis (delta from today)

| Delta | Work |
|---|---|
| `PromptInfo` typed queue | **Net-new** (Decision 1). Design the envelope + in-process queue (Decision 2); retrofit the listener to enqueue instead of BackgroundTasks+Popen. |
| ACP host | **Net-new.** Zero ACP mentions in the old repo. Replaces `runner.py::dispatch_to_opencode`, `scripts/prompt.ps1`, the `orchestratorservice` container, and the `opencode run --attach` call shape. |
| Watchdog | **Rework or retire.** Today parses opencode stderr glyph logs for permission-asks/idle; over ACP the equivalents are protocol events (permission requests, session update stream) — Decision 7. |
| Orchestration prompt | **Rewrite.** 431-line jinja2 match-clause file → open-ended orchestration prompt; workflow bodies stay external in `agent-instructions`. |
| Feature-request path | **Net-new.** Today only the one fixed cycle exists; path (b) creates Epic/Story/Task issues in the existing tracking (Decision 9). |
| Swarm invocation | **Net-new bridge via SwarmSandbox** (Decision 5): sandbox provisions the environment, the driven ACP client runs the swarm from the in-repo swarm assets. |
| Deletion | `orchestratorservice` compose service + Dockerfile serve CMD; `prompt.ps1` attach path; opencode-stderr parsing in `run_stream.py`/`watchdog.py`/`filters.py` trace blacklist. |

## 5. Decisions (owner-reviewed and folded 2026-09-10)

1. **PromptInfo is greenfield.** No sibling repo holds a prior design — net-new, built per the
   recommendation below.
2. **Queue substrate: in-process `asyncio.Queue` first.** Matches the single-container
   deployment, no new dependencies; the `PromptInfo` envelope is designed for later export, and
   durability is added only when a missed webhook actually hurts.
3. **Autonomy model (from research, spike to verify):** the host auto-selects `allow_always` in
   `session/request_permission` plus opencode's `permission` config as belt-and-braces, copying
   acpx's policy shape (`approve-reads` default, per-tool escalation, deny-list for destructive
   tools). Phase-0 must prove the deny path headless, not just the happy path.
4. **Session shape: one cold ACP session per PromptInfo.** Simple and stateless; the swarm is the
   long-running part, not the orchestrator turn. Warm per-repo sessions remain a later option.
5. **Swarm execution: Option C — SwarmSandbox provisions the environment; the driven ACP client
   runs the swarm inside it.** Owner-confirmed, and the owner's inference is correct: swarm
   support is thereby decoupled from any specific ACP client. The sandbox provides the harness
   environment (repo clone with the swarm skills/rules/agent assets at a known revision +
   `pwsh`/POSIX toolchain); whichever client the host drives (opencode today) executes the swarm
   from those in-repo assets. The host stays thin — it drives the client, never the swarm.
6. **Beads pipeline routes through the same ACP host** (the shared `_prompt_script_invocation`
   seam), loop logic unchanged.
7. **Dashboard/progress: ACP protocol events only** (`session/update` → the SSE `EventStore` as
   new event types); the opencode-stderr glyph parser is deleted.
8. **Repo topology: new repo `nam20485/swarm-orchestration-service`, cloned from THIS repo
   (swarm-context), for both sides, linked to swarm-context via a fork-style upstream remote**
   — no cross-contamination with the old `orchestrator-service`
   (which remains untouched as the reference implementation to port the listener/webhook code
   from). The clone carries the swarm harness (`swarm`/`swarm-plan` skills, `.zcode/agents`,
   rules), `gh-issue-tracking-init`, and the SwarmSandbox service source (Decision 5) — the
   "Reuse from this repo" note in §3.3 becomes load-bearing here.

   **Linking decision: fork-style upstream remote.** swarm-context
   stays the template/harness source of truth; the orchestration repo is cloned once from it,
   adds `upstream` → swarm-context, and merges `upstream/development` on demand (each sync a
   PR, so contamination is one-directional and reviewed). Alternatives considered and rejected:

   | Mechanism | Pros | Cons |
   |---|---|---|
   | **Fork-style upstream remote — CHOSEN** (clone once; `git remote add upstream <swarm-context>`; periodic `git fetch upstream && git merge upstream/development` as a reviewed PR) | plain git, no submodules; shared ancestry makes merges natural; syncs are explicit, reviewable PRs; orchest repo owns its releases; no tooling | occasional merge conflicts where the orchest repo customizes shared files; history carries the template's past (small repo — negligible) |
   | Template re-clone / cherry-pick | zero coupling | effectively manual copy-paste; no diffable update path; drift is invisible |
   | Git submodule | precise version pinning | detached-pointer confusion, partial checkouts, CI complexity — owner rejects |
   | Extracted shared package + sync script | clean layering | big refactor for a 2-consumer base; still needs the sync discipline it claims to remove |

   Longer-term, if the swarm harness stabilizes, upstream the shared assets into
   `intel-agency/agent-context` (the parent template) and point both repos' `upstream` there —
   same mechanism, one level higher. Cloning agent-context *instead* was rejected: it lacks the
   swarm assets entirely, so the orchest repo would have to re-import them from here anyway.
9. **Feature path (b): new features become new Epic/Story/Task issues in the EXISTING repo's
   existing tracking.** The original app-plan issue was the initial implementation's tracking;
   additional features get their own issues under the existing Projects board and label
   taxonomy, with new milestones as needed — no separate issue-tracking infra, no
   `gh-issue-tracking-init` re-run.
10. **Model routing: nothing is pinned host-side.** All model/agent settings and customization
    come from the ACP client the host drives (its own config, e.g. `opencode.json`); the host
    carries no model defaults.
## 6. ACP research summary (verified 2026-09-10, primary sources)

**Protocol.** ACP v1 is stable (v2 in draft since 2026-07-20 — ignore draft features). JSON-RPC 2.0
over stdio; the **host (client)** launches and drives the **agent (CLI)** subprocess. Host baseline:
answer `session/request_permission`, consume `session/update` notifications (message chunks,
tool_call lifecycle, plan, usage). Agent baseline: `initialize` (version + capability negotiation),
`session/new`, `session/prompt` (returns a stopReason), `session/cancel`. Capability-gated host
extras: `fs/*`, `terminal/*`, `elicitation/create`.

**Client readiness (launcher table).**

| Agent | Launch | Status |
|---|---|---|
| opencode | `opencode acp --cwd <dir>` (stdio nd-JSON; NOT `serve`) | first-class; docs claim full feature parity over ACP; registry v1.18.30 (local 1.18.29); repo now `anomalyco/opencode`; `/undo`+`/redo` unsupported over ACP |
| Kilo Code | `kilo acp` | shipped; registry v7.5.16 |
| Qwen Code | `qwen --acp` | graduated from `--experimental-acp` (2026-01-06); local `--help` confirms; also has `--approval-mode {plan,default,auto-edit,auto,yolo}` (ACP interaction unverified) |
| Gemini CLI | `gemini --acp` | built-in, graduated (`--experimental-acp` deprecated); registry v0.59.0 |
| Claude Code | `claude-agent-acp` adapter | no native ACP (open request anthropics/claude-code#6686); adapter maintained by the protocol org |
| ZCode | community bridge only (`william0wang/zcode-acp`) + open official request (zai-org/feedback#571) | none official — the swarm stays ZCode-native until this changes |

**Python SDK for the host.** `agent-client-protocol` (official, protocol org) — **0.12.1**
(2026-08-16), Python ≥3.10,<3.15; `acp.client`/`acp.agent` async base classes + Pydantic schemas +
`acp.contrib` (session accumulators, **permission brokers**, tool-call trackers); working host
example at `examples/client.py` (`connect_to_agent` → `initialize(PROTOCOL_VERSION)` →
`new_session` → `prompt`). Official but deliberately **pre-1.0** (TS/Rust SDKs are the 1.0 ones) —
pin the exact version and expect 0.x churn. TypeScript SDK is the battle-tested alternative if the
service ever moves off Python.

**Autonomy.** The protocol makes the host the permission authority: `session/request_permission`
carries options `allow_once | allow_always | reject_once | reject_always` — an autonomous host may
auto-select. Belt-and-braces: opencode's `permission` config (allow/ask/deny per tool, works
identically over ACP) can be set so requests never fire. Prior art to copy:
**[`acpx`](https://github.com/openclaw/acpx)** (headless ACP client for orchestrators) — permission
modes `--approve-all` / `--approve-reads` (default) / `--deny-all` plus per-tool JSON policy
(`autoApprove`/`autoDeny`/`escalate`/`defaultAction`).

**Residual unknowns (spike must confirm):** exact opencode floor version for `acp` (docs archived
2025-10-29; releases mention ACP back to v0.15.10); whether TUI `--auto` applies to `acp` mode
(use the config route); the purpose of `acp --port/--hostname/--mdns/--cors` flags (unexplained in
docs — likely a companion endpoint).

## 7. Implementation plan (phased)

- **Phase 0 — Bootstrap + spikes (new repo `nam20485/swarm-orchestration-service`, ~1 session each)**
  0. Bootstrap: clone this repo (post-plan rev) to `nam20485/swarm-orchestration-service`, add
     `upstream` → swarm-context per Decision 8, port the webhook listener + GitHub auth from the
     old repo (reference only), and stand up the compose skeleton (listener + Caddy proxy).
  1. ACP spike: drive `opencode acp --cwd <scratch>` from a Python host script on
     `agent-client-protocol==0.12.1` (pinned) — initialize → new_session → one prompt → collect
     `session/update` → stopReason; then prove the permission deny path headless (request_permission
     auto-reject, and the opencode `permission`-config belt-and-braces). Exit: working spike
     script + §6 residual unknowns resolved (floor version, `--auto` scope, acp network flags).
  2. PromptInfo design doc (envelope fields, in-process queue, durability posture) per Decisions 1–2.
- **Phase 1 — Queue seam (no behavior change)**: define `PromptInfo`; listener enqueues;
  consumer dequeues into the *existing* dispatch path. EventStore gains `prompt_queued`/
  `prompt_consumed` events. Exit: webhook→dispatch flows through the queue; dashboard shows it.
- **Phase 2 — ACP host replaces dispatch**: host launches opencode over ACP per PromptInfo
  (cold session per Decision 4, no host-side model pins per Decision 10); no `opencode serve`
  container ever exists in the new repo — port only the listener/webhook side, implement the
  host fresh; watchdog needs port only if idle detection is not subsumed by protocol events
  (Decision 7). Exit: label dispatch end-to-end over ACP.
- **Phase 3 — Open-ended orchestration prompt**: implement the pseudo-code workflow prompt
  (no clause table to replace in the new repo — the old jinja2 file is the regression reference);
  agent decides progression from live tracking state. Exit: the label matrix driven without
  clause matching.
- **Phase 4 — Paths (a) and (b) + swarm bridge**: new-app path (plan → tracking-init → swarm)
  and feature path (plan → new Epic/Story/Task issues in the existing tracking per Decision 9);
  swarm bridge per Decision 5 — SwarmSandbox provisions the sandbox, the driven ACP client runs
  the swarm from the cloned repo's swarm assets. Exit: both paths demonstrated end-to-end on a
  scratch repo.
- **Phase 5 — Hardening & docs**: e2e smoke in the simulator, dashboard event polish, README/
  AGENTS/GEMINI-equivalent docs, version bump; decommission plan for the old orchestrator-service
  stack (its webhook receiver/`opencode serve` containers stop when the new listener takes the
  Caddy route).

Each phase lands as its own PR to `nam20485/swarm-orchestration-service`; swarm-context-side work
is already landed (`swarm-plan`, inhibitors, SwarmSandbox) and flows in via `upstream` merges.

## 8. Risks

- **ACP maturity drift** (protocol/clients evolving): mitigate with the Phase-0 spike before any
  queue/host code, and keeping the host thin (one client interface).
- **Python SDK is pre-1.0** (0.12.x, breaking changes across minors): pin the exact version,
  vendor the lockfile, and keep the host's SDK surface small (client base class + schema only) so
  bumps are mechanical.
- **Autonomy vs fail-closed permissions**: the single biggest behavioral guarantee to preserve;
  spike must prove the deny path, not just the happy path.
- **Porting drift from the old repo**: the old `orchestrator-service` (dirty tree, reference
  only) keeps moving — snapshot the relevant files at Phase 0 and treat §2's map as of
  `2bd6d06`; re-verify listener behavior against the live repo before porting each piece.
- **Fork-style upstream conflicts**: upstream merges will conflict wherever the orchest repo
  customizes shared template files (README, rules) — keep template-file edits minimal upstream of
  product code directories so merges stay mechanical.
- **Two engines diverging**: if BeadsLoop is left un-ported, the new repo simply lacks it —
  Decision 6 says port it through the same host seam; if deferred, track it explicitly.
- **Prompt regression**: the old clause table, for all its rigidity, is battle-tested; keep its
  label matrix as the Phase 3 regression checklist.
