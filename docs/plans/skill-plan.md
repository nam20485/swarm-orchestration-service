# Plan: Natural-Language Orchestration Skill

Status: revised — Option A selected; every open question is answered by the owner and recorded under Design decisions
Date: 2026-09-15 · Revised: 2026-09-25
Evidence base: `development` @ `cf5b83d`, cross-referenced against `docs/plans/skill-plan-review.md`. Every launcher script this plan delegates to is on `development` (PR #20 merged), so nothing here is gated on a pending merge; the one external dependency is the sibling `../workflow-launch2/plan_docs` slug store.

## Goal

A skill that gives natural-language interaction with the workflow orchestration system. It must support three intents:

1. **Capabilities** — "what can this system do?" The taxonomy reference enumerates **only** what the dispatch gate recognises: `_LABEL_PREFIXES = ("orchestration:", "gh-issue-tracking:")` and `_LABEL_EXACT = {"implementation:ready", "implementation:complete"}` (`src/webhook_receiver/filters.py:25-26`) plus `_DIRECT_BODY_LABEL = "gh-issue-tracking:direct-body"` (`:36`) — the 9 labels in **Label taxonomy** below. The remaining 23 entries of `.github/.labels.json` go under a separate non-triggering heading. "Workflow catalog" is not a deliverable: `.github/workflows/` here is `ci.yml`, `droid.yml`, `droid-review.yml` — no orchestration workflow (the `orchestrator-agent.yml` guard whose logic `filters.py:11-16` replicates in a comment lives in the seeded clones), both index modules contain zero `orchestration:` matches, and `src/webhook_receiver/prompt_builder.py:8` states the design is "never from a hardcoded label→label clause table". What exists, and what intent 1 reports instead, is the four label classes `build_orchestration_prompt` documents (`src/webhook_receiver/prompt_builder.py:206-215`) plus its no-match fallthrough, and the run modes and endpoints. Publishing a canonical catalog is prerequisite work outside this plan.
2. **How to use** — setup, endpoints, env vars, troubleshooting, answered by routing into `docs/usage.md` and the `README.md` Endpoints table rather than restating them.
3. **Initiate an app + workflow** — the scripted `plan_docs` slug launch path, taking **owner + visibility as a validated input pair**: a private repo is supported only under `-Owner intel-agency`, every other owner must be `-Visibility public` (`scripts/create-repo-agent-context.ps1:17-21`, enforced by `Test-OwnerVisibilityPolicy` at `:181`, before any `gh` call and under `-DryRun` too). The skill must refuse or warn rather than produce a repo whose dispatch workflows can never run.

Explicitly **not** folded into the `swarm` skill: swarm stays focused on goal-driven delegation; this skill is the front door to the service.

## Investigation findings

### What feeds prompts onto the queue

Key structural fact: the `PromptInfo` queue has exactly **one producer** — `POST /webhooks/github`. `src/webhook_receiver/app.py:262` builds the envelope and `:274` is the sole `queue.enqueue(info)` call in the codebase. The envelope's `source` field is `Literal["github_webhook"]` (`src/webhook_receiver/prompt_queue.py:50`); there is no admin/enqueue endpoint. Everything else either *manufactures the GitHub event* that reaches that route, *bypasses the queue* to drive the ACP host directly, or is a local-harness path that never touches the service.

| # | Entry point | Mechanism | Feeds queue? |
|---|---|---|---|
| 1 | GitHub webhook deliveries | `issues.labeled` by a non-bot with a dispatch-triggering label (`orchestration:*`, `gh-issue-tracking:*`, `implementation:ready`, `implementation:complete`). `gh-issue-tracking:direct-body` additionally needs the `DIRECT_BODY_ALLOWED_SENDERS` allowlist, and that gate is **fail-closed when unset** — `src/webhook_receiver/filters.py:97-104` returns `direct-body dispatch disabled (set DIRECT_BODY_ALLOWED_SENDERS to enable)`, and unset is the default state of a fresh install. The gate also matches the **issue's full label set**, not only the triggering label, so a stale `direct-body` label keeps gating every later label event on that issue. Filtered deliveries still answer `202` (`src/webhook_receiver/app.py:245`), so the HTTP status never distinguishes accepted from ignored — only the `reason` field and `/events` do. HMAC-verified, gated by `filters.py`, prompt built by `prompt_builder.py`. | Yes — the only direct feeder |
| 2 | Scripted `plan_docs` slug launch | `scripts/create-repo-agent-context.ps1 -Slug <slug>` builds the repo from the template, then its step 5 calls `scripts/trigger-gh-issue-tracking-init.ps1` with `Labels = @('gh-issue-tracking:direct-body')` and `BootstrapLabelsFile` (`scripts/create-repo-agent-context.ps1:338-344`) — **not** `create-dispatch-issue.ps1` directly. Gated by `-TriggerHierarchyInit`, default `$true`. | Indirectly, via path 1 |
| 3 | Generic dispatch on an existing repo | `scripts/trigger-gh-issue-tracking-init.ps1` — its header states "this is the only dispatch trigger". Every label in `-Labels` is bootstrapped from `-BootstrapLabelsFile` by `Ensure-DispatchBootstrapLabel` (from `scripts/dispatch-labels.ps1`), created on the target repo if missing, **before** being attached. It wraps `scripts/create-dispatch-issue.ps1`, and documents `-Labels 'orchestration:dispatch'` as "the legacy orchestration method". | Indirectly, via path 1 |
| 4 | Standalone stage-1 launcher | `scripts/create-repo-with-plan-docs.ps1` (`-RepoName` / `-Owner` / `-PlanDocsDir` / `-CloneParentDir`, own `-DryRun` / `-Yes`). Wrapped by row 2 — **not** an alternative entry point; the skill must not offer both. | No — creates the repo, files nothing |
| 5 | `swarm` skill (`$swarm`, `/swarm plan`) | ZCode-harness interactive skills: wizard → `plan_docs/application_plan.md` → `/gh-issue-tracking-init` → swarm loop. | No — local to the harness; labels it applies can seed later webhook dispatches |

Lesser-known feeders/bypasses (the "third one" candidates):

- `scripts/trigger-gh-issue-tracking-init.ps1` — **the recommended generic dispatch primitive.** Prefer it over the raw issue-filer because it bootstraps labels first.
- `scripts/create-dispatch-issue.ps1` — the lower-level primitive that trigger wraps: files any issue with any labels on any repo. Used directly, a `gh-issue-tracking:direct-body` launch **fails on any repo that has not run `scripts/import-labels.ps1`**, because the label does not yet exist to be attached.
- `src/webhook_receiver/acp_smoke.py` — CLI that builds a synthetic `PromptInfo` and calls `AcpHost.run` directly (bypasses webhook, gate, queue).
- `scripts/e2e-orchestration.ps1` — hermetic simulator: POSTs locally signed synthetic deliveries to the real listener.
- `src/webhook_receiver/sandbox_probe.py` — workspace-provisioning probe only.

### Query surfaces (what the skill can read to answer questions)

- `GET /events` SSE — replay backlog then live fan-out from an in-memory ring buffer, `maxlen: int = 1000` (`src/webhook_receiver/event_store.py:66`); the only structured view of orchestration state.

  **Reachability — it is not on the public surface.** `Caddyfile:30-40` routes only `/webhooks/github` and `/health`, both `reverse_proxy 127.0.0.1:8080`, and the catch-all answers `respond "Not Found" 404`. `https://<public host>/events` therefore returns a 404 body, never orchestration data. In the host-run posture the listener is on `127.0.0.1:8080`, and that is where the stream is read: `docs/usage.md` §6 already states the rule and the remedy — "`/events` is listener-local by design — it is not routed through the public Caddy surface. Reach it on the listener port directly (host run), or via an SSH tunnel / tailnet serve." A status wrapper defaults to `http://127.0.0.1:8080/events` and reaches a remote listener through an SSH tunnel or tailnet serve.

  **Read pattern:** SSE is an open stream — a status command must connect, consume the replay backlog, and disconnect at the keepalive boundary (`WEBHOOK_EVENTS_KEEPALIVE`, default 15 s) rather than block.

  **Durability:** the buffer is a plain `deque`, empty after every restart. `gh` issue state is the historical record; `/events` is the recent window only.
- `src/webhook_receiver/README.md` — the event-name table that `src/webhook_receiver/app.py:17` calls "the single source of truth, mirrored by …"; the authoritative capability doc for `/events`.
- Queue dedup window is **1024 deliveries** (`_DEDUP_CAPACITY`, `src/webhook_receiver/prompt_queue.py:35`, documented at `docs/usage.md` §7) — the answer to "why didn't my re-label fire".
- `scripts/query.ps1` — PR review-thread manager (not a state query).
- `.agents/skills/swarm/scripts/swarm-state.ps1 status` — local swarm-run state (`.swarm/<run-id>/state.json`, gitignored).
- `logs/*.jsonl` and `gh-init-*.log` — forensic run logs from the launch pipeline and from gh-issue-tracking-init (`.gitignore:14` and `.gitignore:4`). Write-only today: `scripts/logging.ps1` exposes `Start-RunLog` / `Write-RunLog` / `Complete-RunLog` and no reader.
- `gh issue list` / `gh pr list` / Projects board — canonical live tracking state. Caveat: the `agent:*` and `state:*` labels in `.github/.labels.json` are applied and read by **no code in this repo** and matched by nothing in `filters.py`, so they are not a status surface, and the skill must not imply they are.
- `local_ai_instruction_modules/ai-*.md` — pointer tables to the remote `nam20485/agent-instructions` workflows. Both forbid mirroring at line 10: `ai-dynamic-workflows.md:10` — "Agents MUST resolve dynamic workflows from the remote canonical repository. **Do not use local mirrors.**"; `ai-workflow-assignments.md:10` is the same rule for workflow assignments "(by shortId)". Neither file contains an `orchestration:` match.

### Label taxonomy

`.github/.labels.json` holds **32** labels. Exactly **9** dispatch anything:

| Dispatch-triggering label | Matched by | Prompt class (`src/webhook_receiver/prompt_builder.py:206-215`) |
|---|---|---|
| `gh-issue-tracking:direct-body` | `src/webhook_receiver/filters.py:36`, sender-allowlisted at `:97-104` | issue body verbatim |
| `orchestration:dispatch` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `orchestration:plan-approved` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `orchestration:epic-ready` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `orchestration:epic-implemented` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `orchestration:epic-complete` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `orchestration:epic-reviewed` | `filters.py:25` prefix | named orchestration lifecycle workflow |
| `implementation:ready` | `filters.py:26` exact | implementation path for the tracked work item |
| `implementation:complete` | `filters.py:26` exact | implementation path for the tracked work item |

The **live vocabulary** is the `.agents/skills/gh-issue-tracking-init/assets/labels.json` set — **19** labels, of which only `gh-issue-tracking:direct-body` appears in the table above.

**Deprecated but still live in code.** The other 8 dispatch-triggering labels above — the six `orchestration:*` and the two `implementation:*` — are legacy relative to that 19-label set (`scripts/trigger-gh-issue-tracking-init.ps1` calls `orchestration:dispatch` "the legacy orchestration method"), yet `filters.py:25-26` still matches them and `prompt_builder.py` still routes them. The taxonomy reference must carry both truths: mark them deprecated, and do not present them as the way forward. Removing them from the gate is out of scope — it is a change to the webhook listener (Non-goals).

**Non-triggering labels.** The remaining 23 entries of `.github/.labels.json` are GitHub defaults (`bug`, `wontfix`, `good first issue`, …), the copilot/agent/state vocabulary (`agent:queued`, `state:planning`, …), and bare hierarchy names (`epic`, `story`). No code matches them; applying one answers `202` with `webhook_filtered` and dispatches nothing.

### Gap

The material exists and is well-structured. `docs/usage.md` already answers "how do I use it" end to end — §1 Pick a run mode · §2 Configure · §3 Expose it to the internet · §4 Wire the GitHub App · §5 Trigger a run · §6 Observe · §7 Troubleshoot · §8 Operational notes · §9 Verify changes before deploying — and `README.md:45-51` has a ready Endpoints table.

What is missing is **routing and initiation**: no conversational entry point selects among those documents, and no surface walks a user from "start an app + workflow" to the correct scripted path. This is a navigation problem, not a documentation-authorship problem — which is why `references/` is an index rather than a copy (D4).

Nor is there a dashboard to build on: `docs/architecture.md:122-123` records that `/events` "is the surface a dashboard consumes; none is built yet (the old stack's dashboard was not ported)". See D7.

## Proposed shape

New skill at `.agents/skills/orchestrate-swarm/`, `name: orchestrate-swarm` (D1), following repo conventions (`.agents/rules/skills.md`): Agent Skills spec compliant, trigger-rich `description`, `SKILL.md` under 500 lines, scripts-over-prose, validated with `uvx --from skills-ref agentskills validate ./orchestrate-swarm`.

The skill is **self-contained** — `.agents/rules/skills.md:50`: "The skill's whole job should still be reproducible from its directory alone — no external file dependencies outside the skill's own `scripts/`". The thin-wrapper design stays (re-implementing the launchers would be far worse), but out-of-skill dependencies are **declared, not assumed**, following the precedent at `.agents/skills/swarm-plan/SKILL.md:4`:

```yaml
compatibility: Requires scripts/create-repo-agent-context.ps1 and
  scripts/trigger-gh-issue-tracking-init.ps1 in the target repo, plus the
  ../workflow-launch2/plan_docs slug store for the -Slug path.
```

Both delegates exist on `development` @ `cf5b83d`. The slug store is the one external path dependency: `-PlanDocsRoot` defaults to `(Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs')` (`scripts/create-repo-agent-context.ps1:107`), and the skill must surface that when the slug directory is absent rather than fail obscurely.

Components:

- `SKILL.md` — intent routing (capabilities / how-to / initiate / status) and the approval gate; prose stays thin.
- `references/` — a thin **index** into `docs/usage.md`, `README.md` and `.github/.labels.json`, plus the facts no single document states together: the `/events` reachability constraint, the owner/visibility policy, and the 9-vs-19-vs-23 label split. Material is **copied or generated into `references/`, never read from repo `docs/` paths at invocation time** (D4). `local_ai_instruction_modules/` content is **not** mirrored here — store only the pointer (repo `nam20485/agent-instructions`, branch, `ai_instruction_modules/<dir>/`, resolve by shortId), because those files forbid local mirrors.
- `scripts/` — thin wrappers, not re-implementations:
  - launch: delegate to `scripts/create-repo-agent-context.ps1` (the `plan_docs` slug path, which reaches the queue through `scripts/trigger-gh-issue-tracking-init.ps1`); never call `scripts/create-dispatch-issue.ps1` directly for a dispatch. Validate the owner + visibility pair before any `gh` call, surface `-PlanDocsRoot` when the slug directory is missing, and route to `/swarm-plan` when the user has no plan yet (D2).
  - pre-flight: check `DIRECT_BODY_ALLOWED_SENDERS` is set before offering any `direct-body` launch — unset means dispatch is fail-closed and the launch will silently do nothing — and account for labels already on the issue, since the gate matches the full label set.
  - status: default to `http://127.0.0.1:8080/events`, drain the replay backlog to the keepalive boundary, fall back to `gh` state, and report which path it used and why it failed when `/events` is unreachable. The forensic logs stay raw text — no structured log reader is implied by this plan.

Open follow-up, not a defect in this plan: the validator identifier `skills_must_be_self_contained` cited at `.agents/rules/skills.md:50` resolves to nothing in this repo (grep: no matches outside the rule and this document). The rule should cite a real check.

## Design decisions

**D1 — Name: `orchestrate-swarm` (was OQ1).** The owner's choice, and it works as the spec requires: `name` must match the directory name, lowercase `a-z`, `0-9`, hyphens only, no leading, trailing or consecutive hyphens, ≤ 64 chars (`.agents/rules/skills.md:26`). Directory, `name` field and invocation form all read `orchestrate-swarm`. Rejected candidates: bare `orchestrate` — it collides in reading order with three installed user-level skills (`orchestrate-dynamic-workflow`, `orchestrate-new-project`, `orchestrate-project-setup`), none of which touch this service; and `swarm-orchestration` — it reads as swarm-owned, contradicting Goal's separation.

**D2 — Initiation scope: the scripted `plan_docs` slug path, with a route to `/swarm-plan` (was OQ2, absorbing OQ6).** `/orchestrate-swarm` opens the conversation; the user then either supplies a `plan_docs` slug name or asks for help designing the plan, in which case the skill routes to the existing `/swarm-plan` wizard, which writes `plan_docs/application_plan.md`. The wizard is not re-implemented here. Generic dispatch (`trigger-gh-issue-tracking-init.ps1` with an arbitrary repo + `-Labels` + body) stays documented as the mechanism the slug path drives internally; the skill does not expose it as a free-form initiate surface, because that is an arbitrary privileged write to any repo the token can reach.

**D3 — Status querying is in v1 (was OQ3).** Read-only: `/events` on the listener port, `gh` issue/PR/board state, and the gate and label facts above. No new queue surface, no new log tooling.

**D4 — `references/` is copied or generated, never read live (was OQ4).** Decided by `.agents/rules/skills.md:50` — "read `docs/` at invocation time (skill then only works from this repo)" is precisely the option that rule exists to prevent. Consequence: `references/` can drift, so it holds an index plus the cross-document facts, not capability prose.

**D5 — One confirmation gate (was OQ5).** One `-DryRun` preview, then run. This is already the launcher precedent: `-DryRun` is forwarded to every invoked script (`scripts/create-repo-agent-context.ps1:76-77`) and is deliberately validated to bail on the same failures as a real launch (`:17-21`), while `-Yes` (`scripts/create-repo-agent-context.ps1:122`) and `ShouldProcess` in the scripts it delegates to form the separate non-interactive layer. Per-stage prompting would duplicate gating the scripts already perform.

**D6 — Label vocabulary is the 19-label gh-issue-tracking-init set; the 8 legacy dispatch labels are documented as deprecated but still live (was OQ7).** Only `gh-issue-tracking:direct-body` is common to both sets. The six `orchestration:*` and two `implementation:*` labels remain matched by `filters.py:25-26` and routed by `prompt_builder.py`, so the skill documents them as live-but-deprecated rather than omitting them; retiring them from code is a webhook-listener change and out of scope.

**D7 — A dashboard is a non-goal, not something that was lost.** None exists: `docs/architecture.md:122-123` — `/events` "is the surface a dashboard consumes; none is built yet (the old stack's dashboard was not ported)". The old stack's dashboard was deliberately not carried over; this plan does not revisit that. The `status` wrapper is the minimal `/events` consumer.

OQ6 — whether the skill should also explain and route to the ZCode-local planning path — was a duplicate of OQ2. Its answer is the same yes: route to `/swarm-plan`. It is folded into D2 rather than decided separately.

## Options

### Option A — Knowledge + launch skill (SELECTED)

Skill covers all three intents; initiation is the scripted `plan_docs` slug path behind one explicit confirmation gate before anything creates a repo or labels an issue (D2, D5). Status querying is read-only and included (D3).

- Pros: fills the whole identified gap; matches existing skill conventions; no service changes required.
- Cons: `references/` can drift from `docs/`. Mitigated by D4 — `references/` is a thin index plus the cross-document facts, copied or generated rather than read live, with `local_ai_instruction_modules/` excluded from mirroring entirely; a freshness check closes the remainder.

### Option B — Query/status only, defer initiation

Skill answers capabilities/how-to/status; initiation stays documented but manual.

- Pros: smallest blast radius; no repo-creation automation to gate.
- Cons: misses the stated "initiate an app and workflow" requirement.

### Option C — Full agent (subagent definition) instead of a skill

- Rejected: an agent adds orchestration overhead for what is fundamentally routing + reference + scripted calls; a skill is sufficient, as suspected in the original note.

### Also rejected

- Extending the `swarm` skill — violates the separation-of-concerns decision (swarm already split planning out into `swarm-plan` for the same reason).
- Adding an admin/enqueue endpoint to the service — unnecessary; the issue-label indirection is the designed, auditable path and keeps the sender allowlist model intact.

## Acceptance criteria

Done when:

1. The **capabilities** intent answers correctly: it enumerates exactly the 9 dispatch-triggering labels, puts the other 23 under a non-triggering heading, presents no non-triggering label as a way to start a run, describes `agent:*` / `state:*` as unwritten rather than as status, and never claims a static workflow catalog exists.
2. The **how-to** intent answers setup / endpoints / env vars / troubleshooting by routing to `docs/usage.md` and `README.md`, and the **initiate** intent reaches `scripts/create-repo-agent-context.ps1 -Slug` without inventing a third launcher.
3. The **initiate** path refuses, or warns explicitly, when `DIRECT_BODY_ALLOWED_SENDERS` is unset — it never files a dispatch that `filters.py` rejects fail-closed.
4. The **initiate** path validates the owner + visibility pair before any `gh` call and refuses a private repo under a non-`intel-agency` owner.
5. The **status** path degrades gracefully when `/events` is unreachable: it names the endpoint it tried and why it failed (a Caddy `Not Found` is reported as "`/events` is not on the public surface", never parsed as orchestration data), falls back to `gh` state, and returns within the keepalive window instead of blocking on the open stream.
6. `uvx --from skills-ref agentskills validate ./orchestrate-swarm` passes.
7. New `scripts/*.ps1` under the skill ship Pester tests and the > 85% coverage gate stays green — noting that `validation.ps1:177` `$coveragePaths` currently enumerates only the `gh-issue-tracking-init`, `update-powershell-standard` and `swarm` script directories (`$testPaths` at `validation.ps1:169` likewise), so wiring the new test directory into the gate is a work item here, not an automatic outcome.
8. `pwsh ./validation.ps1 -Step build` exits 0.

## Effort and rollback

**Estimate — roughly 3–5 focused days**, sized to `SKILL.md` + `references/` + the launch and status wrappers + a Pester suite:

| Slice | Estimate |
|---|---|
| `SKILL.md` + `compatibility:` + intent routing and the single gate | 0.5 d |
| `references/` (thin index, generated snapshot, pointer-only module entries) | 1 d |
| Launch wrapper (`-Slug` path, pre-flight checks, `/swarm-plan` route) | 1 d |
| Status wrapper (`127.0.0.1:8080` default, backlog drain on `WEBHOOK_EVENTS_KEEPALIVE`, `gh` fallback) | 1 d |
| Pester suite + coverage-gate wiring + validator pass | 0.5–1 d |

Biggest risk is the **status** wrapper: it depends on operational reachability the skill does not control, which is why acceptance criterion 5 is a graceful-degradation test rather than a data test.

**Rollback:** the skill is one self-contained directory under `.agents/skills/`. Deleting that directory disables it with zero service impact — the webhook listener, queue schema and ACP host are untouched (Non-goals), and the launchers it wraps existed before it and remain callable by hand. No migration, no state, no cleanup.

## Non-goals

- No changes to the webhook listener, queue schema, or ACP host.
- No new queue producers.
- No dashboard (the `GET /events` consumer stays minimal).
- No dashboard is being removed either — none exists: the old stack's dashboard was not ported (`docs/architecture.md:122-123`, D7).
