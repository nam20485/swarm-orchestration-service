# Project Memory

## Current Activity

Current project and its sub-work items that we are working on actively. Items move to "Completed Work Items" when done.

### Project: Swarm-orchestration-service (this repo, bootstrapped 2026-09-10)

- **Repo purpose**: implement [`docs/plans/orchestrator-service-simplification.md`](../docs/plans/orchestrator-service-simplification.md) (APPROVED 2026-09-10, all 10 §5 owner decisions folded) — net-new typed `PromptInfo` async queue feeding an ACP host (opencode first) that replaces the old `orchestrator-service` dispatch; open-ended orchestration prompt; two entry paths (new app → `gh-issue-tracking-init` → swarm; new feature → Epic/Story/Task issues in existing tracking → swarm); swarm execution via SwarmSandbox (Decision 5, Option C). Requirements source: [`docs/plans/orchestrator-service-integration.md`](../docs/plans/orchestrator-service-integration.md). Webhook listener + GitHub auth get ported from `nam20485/orchestrator-service` (@`2bd6d06`, reference only — that repo stays untouched).
- **Base re-seeded correctly (2026-09-10)**: first attempt landed as a GitHub-template-route repo (single squashed "Initial commit" — no shared ancestry); fixed in place by grafting `upstream/development` (`0d9c7dd`) under the working tree via soft reset + force-push (trees were identical, zero drift). Remotes now: `origin` → `nam20485/swarm-orchestration-service`, `upstream` → `nam20485/swarm-context`. Fork-style `upstream` merges have real shared ancestry per plan §5 Decision 8.
- **Clone de-contamination done (2026-09-10)**: pruned parent-template Class 2 state — `docs/plans/.complete/` (upstream's swarm-harness build plans), `docs/plans/new templates/` (superseded by the `swarm-plan` skill's bundled asset), `docs/swarm-metrics.md` reset to a scaffold (baseline telemetry lives upstream), memory reset, `swarm-context.code-workspace` renamed to `swarm-orchestration-service.code-workspace`, README lint-scope line trimmed. Kept deliberately: both orchestrator-service plan docs, `docs/plans/SWARM_PARALLEL_COMPILATION_PLAN.md` (referenced by the co-tenancy rule in `.zcode/agents/swarm-orchestrator.md`), and all Class 1 infra (swarm skills/agents/rules, `gh-issue-tracking-init`, `src/SwarmSandbox/`, scripts, validation/CI).
- **Next**: Phase 0 per the plan — bootstrap (compose skeleton, port the webhook listener from the old repo reference), ACP spike on pinned `agent-client-protocol==0.12.1` incl. headless deny-path proof, PromptInfo design doc.

## Completed Work Items

(none yet in this repo — upstream history lives in `nam20485/swarm-context` → `.agents/memory.md`.)

## Decisions

- **Repo linking: fork-style upstream remote** (plan §5 Decision 8): swarm-context stays the swarm-harness source of truth; this repo merges `upstream/development` on demand, each sync a reviewed PR. Keep edits to shared template files (README, `.agents/rules/`, `.zcode/agents/`, AGENTS.md) minimal and upstream of product code so merges stay mechanical.
- **ZCode MCP config cannot be committed with secrets** (re-verified 2026-09-10, docs + CLI probe): `config.json` supports no env-var interpolation (`${VAR}`/`{env:VAR}` absent from the official MCP docs and the CLI bundle) — `env`/`headers` values are literal. Pattern: real `.zcode/config.json` stays gitignored; `.zcode/config.example.json` (placeholders) is the committed form. OpenCode's `opencode.jsonc` DOES support `{env:VAR}`, which is why `.opencode/` config can be committed.

## Remember To Do

- **`thoughtLevel: off` blocks GLM-5.3-Flash worker spawning entirely** (carried from upstream, observed 2026-09-10): frontmatter is ignored and spawning fails with "Reasoning effort 'off' is not supported". Either drop it from the worker defs and accept thinking costs, pin worker models that support off, or get harness support. Resolve before the next swarm run.
- **Align `swarm-state.ps1` budget with concurrent-not-all-time semantics** (carried from upstream): `start-round` enforces cumulative spawns; user clarified the budget is CONCURRENT subagents. Track in-flight (pending/running) tasks, update `.agents/rules/swarm.md` § Budget + the skill.
- **Per-run telemetry archiving** (carried from upstream): subagent model-io JSONLs prune on completion — automate copying each worker's JSONL to `.swarm/<run-id>/telemetry/` so the analyst doesn't fall back to `db.sqlite`.
- **SwarmSandbox AppHost has never been run end-to-end by any gate** (carried known-gap from the upstream build): do a manual `dotnet run` smoke when the service is next needed.
- **GitHub hygiene for THIS repo**: upstream's readiness work (label import, branch-protection ruleset, milestones/Projects board) does not carry — verify/recreate before PR flow starts (`.agents/rules/source-control.md` expects milestone + project on PRs).
