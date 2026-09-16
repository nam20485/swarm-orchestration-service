# Plan: Natural-Language Orchestration Skill

Status: draft — pending owner decisions (see Open Questions)
Date: 2026-09-15

## Goal

A skill (name TBD) that gives natural-language interaction with the workflow
orchestration system. It must support three intents:

1. **Capabilities** — "what can this system do?" (label taxonomy, workflow
   catalog, run modes).
2. **How to use** — setup, endpoints, env vars, troubleshooting.
3. **Initiate an app + workflow** — at minimum the scripted `plan_docs` slug
   launch path.

Explicitly **not** folded into the `swarm` skill: swarm stays focused on
goal-driven delegation; this skill is the front door to the service.

## Investigation findings

### What feeds prompts onto the queue

Key structural fact: the `PromptInfo` queue has exactly **one producer** —
`POST /webhooks/github` (`src/webhook_receiver/app.py:262`). The envelope's
`source` field is `Literal["github_webhook"]`
(`src/webhook_receiver/prompt_queue.py:50`); there is no admin/enqueue
endpoint. Everything else either *manufactures the GitHub event* that reaches
that route, *bypasses the queue* to drive the ACP host directly, or is a
local-harness path that never touches the service.

| # | Entry point | Mechanism | Feeds queue? |
|---|-------------|-----------|--------------|
| 1 | GitHub webhook deliveries | `issues.labeled` by a non-bot with a workflow label (`orchestration:*`, `gh-issue-tracking:*`, `implementation:ready\|complete`); `direct-body` additionally needs the `DIRECT_BODY_ALLOWED_SENDERS` allowlist. HMAC-verified, gated by `filters.py`, prompt built by `prompt_builder.py`. | Yes — the only direct feeder |
| 2 | Scripted plan_docs slug launch | `scripts/create-repo-agent-context.ps1 -Slug <slug>` builds the repo from the template, then files a dispatch issue (`gh-issue-tracking:direct-body`, body `/gh-issue-tracking-init`) via `scripts/create-dispatch-issue.ps1`. | Indirectly, via path 1 |
| 3 | Swarm skill (`$swarm`, `/swarm plan`) | ZCode-harness interactive skills: wizard → `plan_docs/application_plan.md` → `/gh-issue-tracking-init` → swarm loop. | No — local to the harness; labels it applies can seed later webhook dispatches |

Lesser-known feeders/bypasses (the "third one" candidates):

- `scripts/create-dispatch-issue.ps1` — generic CLI primitive: files any
  issue with any labels on any repo; combined with the direct-body label it
  injects a verbatim prompt (allowlist-gated).
- `src/webhook_receiver/acp_smoke.py` — CLI that builds a synthetic
  `PromptInfo` and calls `AcpHost.run` directly (bypasses webhook, gate,
  queue).
- `scripts/e2e-orchestration.ps1` — hermetic simulator: POSTs locally signed
  synthetic deliveries to the real listener.
- `src/webhook_receiver/sandbox_probe.py` — workspace-provisioning probe only.

### Query surfaces (what the skill can read to answer questions)

- `GET /events` SSE — listener-local ring buffer (1000 entries), replay +
  live fan-out; the only structured view of orchestration state.
- `scripts/query.ps1` — PR review-thread manager (not a state query).
- `.agents/skills/swarm/scripts/swarm-state.ps1 status` — local swarm-run
  state (`.swarm/<run-id>/state.json`, gitignored).
- `logs/*.jsonl` — forensic run logs from the launch pipeline; write-only
  today, no reader tooling.
- `gh issue list` / `gh pr list` / Projects board — canonical live tracking
  state.
- `local_ai_instruction_modules/ai-*.md` — static lookup tables of remote
  `nam20485/agent-instructions` workflows.

### Gap

No single surface answers "what can this system do / how do I use it / start
an app + workflow". Capability knowledge is spread across `README.md`,
`docs/usage.md`, `docs/architecture.md`, `.agents/rules/`, and the lookup
tables; initiation is split across manual labeling, the slug pipeline, and
the ZCode-local skills.

## Proposed shape

New skill at `.agents/skills/<name>/` following repo conventions
(`.agents/rules/skills.md`): Agent Skills spec compliant, trigger-rich
`description`, `SKILL.md` under 500 lines, scripts-over-prose, validated with
`uvx --from skills-ref agentskills validate`.

Components:

- `SKILL.md` — intent routing (capabilities / how-to / initiate) and the
  approval gates; prose stays thin.
- `references/` — distilled capability docs (label taxonomy, run modes,
  endpoints, initiation paths) sourced from README/usage/architecture.
- `scripts/` — thin wrappers, not re-implementations:
  - launch: delegate to `scripts/create-repo-agent-context.ps1` (and possibly
    `create-dispatch-issue.ps1` for the generic path);
  - status: read `GET /events`, `gh` state, and optionally `logs/*.jsonl`.

## Options

### Option A — Knowledge + launch skill (recommended)

Skill covers all three intents; initiation supports the slug path and the
generic dispatch-issue path, both with an explicit user-confirmation gate
before anything creates a repo or labels an issue. Status querying is
read-only and included.

- Pros: fills the whole identified gap; matches existing skill conventions;
  no service changes required.
- Cons: `references/` can drift from `docs/` (mitigate: generate or link
  rather than copy; add a freshness check script).

### Option B — Query/status only, defer initiation

Skill answers capabilities/how-to/status; initiation stays documented but
manual.

- Pros: smallest blast radius; no repo-creation automation to gate.
- Cons: misses the stated "initiate an app and workflow" requirement.

### Option C — Full agent (subagent definition) instead of a skill

- Rejected: an agent adds orchestration overhead for what is fundamentally
  routing + reference + scripted calls; a skill is sufficient, as suspected
  in the original note.

### Also rejected

- Extending the `swarm` skill — violates the separation-of-concerns decision
  (swarm already split planning out into `swarm-plan` for the same reason).
- Adding an admin/enqueue endpoint to the service — unnecessary; the
  issue-label indirection is the designed, auditable path and keeps the
  sender allowlist model intact.


  OPTION A

## Open questions

1. **Name** — `orchestrate`? `swarm-orchestration`? Must not collide with
   existing skills or read as swarm-owned. `/orchestrate-swarm`
2. **Initiation scope** — slug path only, or also the generic
   `create-dispatch-issue.ps1` path (arbitrary repo + label + body)? the sctipr or /swarm-plan if you need an agent to walk you throught designing it first. (NOTE: `/orchestrate-swarm` starts the conversation and user can ask about , and then either supply the plan_docs slug nbame, or ask for help with the plan
3. **Status querying** — in scope for v1 (read `GET /events`, `logs/`, `gh`) yes
   or deferred? A `logs/*.jsonl` reader would be new tooling.
4. **References strategy** — copy distilled docs into `references/` (drift
   risk) vs. read `docs/` at invocation time (skill then only works from this
   repo) vs. generated snapshot with a staleness check. skill 
5. **Confirmation gates** — is one explicit approval before repo creation
   enough, or per-stage confirmation (repo → labels → dispatch issue)? 1 is fine
6. **ZCode-local path** — should the skill also explain/route to
   `/swarm plan`, or strictly the service paths? i dont know what this means
7. **Label reconciliation dependency** — `.github/.labels.json` (32 dispatch
   labels) vs. the gh-issue-tracking-init label set (19) is a known
   owner-gated open item; does the skill document both sets as-is or wait? only the new set is relevanr, the other dispatch labels are legacy

## Non-goals

- No changes to the webhook listener, queue schema, or ACP host.
- No new queue producers.
- No dashboard (the `GET /events` consumer stays minimal).


Do we not have dashbaord? What happened to the  old one working one? Dont worry about it rn this is alrady exceeding my threhhold for complexity
