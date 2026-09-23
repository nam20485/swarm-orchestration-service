# Swarm

Rules for the goal-driven agent swarm on the ZCode harness — entry point is the `swarm` skill (`$swarm`), operating protocol is `.zcode/agents/swarm-orchestrator.md`. The optional interactive frontend is the `swarm-plan` skill (`/swarm plan`): it interrogates an app/feature idea into an approved `plan_docs/application_plan.md`, derives the goal(s) for approval, initializes the GH issue-tracking hierarchy via `gh-issue-tracking-init`, then starts the swarm (see [`.agents/skills/swarm-plan/SKILL.md`](../skills/swarm-plan/SKILL.md)).

## Topology

The primary session acts as the orchestrator and spawns worker subagents through the Agent tool — swarm depth is exactly 1. Reason: a ZCode subagent cannot spawn subagents (verified, <https://zcode.z.ai/en/docs/subagents>), so the orchestrator role must run in the primary session; the `swarm-orchestrator` definition's body is adopted by the primary session via the skill (`@`-mentioning it as a subagent gives a solo worker, not an orchestrator).

## Locations

- Agent definitions are real ZCode-format files in `.zcode/agents/` — no symlinks, no canonical copies elsewhere. ZCode-specific definitions are not readable by other harnesses; supporting another harness means generating native definitions for it (deferred until a second harness is chosen).
- The skill lives at `.agents/skills/swarm/` (repo convention; workspace discovery from `.agents/skills/` is empirically confirmed by this repo's existing skills).
- Run state lives under `.swarm/<run-id>/` (`goal.md`, `state.json`, `field-guide.md`) and is gitignored — local-only, never committed.
- Shared worker instructions live in [`.agents/rules/swarm-workers.md`](swarm-workers.md) — the workers' conventions channel (see below).

## Worker types

| Name | Tools | Use for |
|---|---|---|
| `swarm-agent` | Read, Grep, Glob | default / read-only analysis (template to extend) |
| `swarm-implementer` | Read, Grep, Glob, Edit, Write, Bash | any file edit or build |
| `swarm-researcher` | Read, Grep, Glob, WebFetch, WebSearch, Z.AI MCP (`web-reader`, `web-search-prime`, `zread`) | web / docs research |
| `swarm-verifier` | Read, Grep, Glob, Bash | run verification commands for evidence |
| `swarm-reviewer` | Read, Grep, Glob, Bash | diff / quality review |
| `swarm-analyst` | Read, Grep, Glob, Bash | post-wave telemetry: parses subagent session logs, appends metrics to `docs/swarm-metrics.md`, reports ranked anomalies |

No hard type cap (the old ≤5 rule was dropped by user direction, 2026-09-06): every type must be narrowly single-purpose with the smallest sufficient toolset — the narrower the definition, the more focused the worker. All definitions set `injectAgentsMd: false` — workers get their conventions from `.agents/rules/swarm-workers.md` plus the task's Constraints element, not from the primary session's AGENTS.md (whose mandates reference tools they lack). All worker definitions set `model: GLM-5.3-Flash` + `thoughtLevel: off` — extended thinking at the worker level was measured as a cost driver (32K thinking budget + `effort: max` on every request); reasoning belongs at the orchestrator level, worker tasks must be straightforward directions.

## Post-wave analysis

After each wave's workers report, spawn one `swarm-analyst` for the whole wave (never one per agent — cross-referencing sessions is the point). It parses `~/.zcode/cli/agents/<sess>/<agent>/metadata.json` + `~/.zcode/cli/rollout/model-io-sess_subagent_<agent>.jsonl`, appends metrics rows and anomalies to `docs/swarm-metrics.md` (gitignored run artifact, created with a header if missing; the only file it writes), and returns ranked anomalies with one-line fixes. The orchestrator reads that report before composing the next wave — anomalies feed decomposition (contention → re-split by build unit; duplicate discovery → inject excerpts; wasted calls → narrow toolset or tighten Done-when).

## MCP servers

The Z.AI servers (`web-reader`, `web-search-prime`, `zread`) are granted to `swarm-researcher` by full tool name (`mcp__web-reader__webReader`, `mcp__web-search-prime__web_search_prime`, `mcp__zread__get_repo_structure`, `mcp__zread__read_file`, `mcp__zread__search_doc` — ZCode silently ignores wildcards like `mcp__server__*`) plus a `mcpServers: [web-reader, web-search-prime, zread]` declaration that fails fast if a server is not connected. MCP tools are retained only where granted by full name — every other worker is MCP-free by design. The servers are defined project-locally in `.zcode/config.json` (gitignored: real keys, and ZCode config stores values literally with no env-var interpolation) with the committable template `.zcode/config.example.json`; per-server tool documentation lives in [`.agents/rules/tools.md`](tools.md).

## Budget

`swarm-state.ps1` enforces `spawned -ge maxSubagents` only at `start-round`. The orchestrator must check `spawned` vs `maxSubagents` (from `status`) before each spawn batch and never exceed the budget within a round. Default budget: 50.

## Stall and permission rules

- Stall guard: 3 consecutive `not-met` rounds with no task status change → `finish -Status stopped`.
- A worker parked on a permission gate is a blocker with stall-guard handling — `TaskStop` + `record-task -Status failed` — never an indefinite wait. Background spawning keeps it from blocking the session, but the round cannot close until it is resolved or stopped.
- Swarm sessions run in **Full access** (Shift+Tab) or with the needed command types pre-granted via Always Allow ("Always allow for this project" included). Never rely on the 5-minute auto-continue — it does not apply to permission requests; they wait indefinitely. "Edit automatically" still confirms every command and is not sufficient.
- Because Full access removes the confirmation layer for the whole session, only run swarms on trusted goals (sandboxed swarm execution was deferred by user decision, 2026-09-05).

## Verdicts

`end-round -Verdict met` is permitted only after a cold `swarm-verifier` task for that round reports `PASS` against the goal's success criterion with verbatim command output — cold means never the worker that did the work, and tasked with only the criterion + verification commands, not the implementer's summary. The orchestrator records verdicts; it never invents one. `end-round met` is the success path and must not be followed by `finish`; `finish -Status stopped` is for stall/interrupt/recording the end of a budget-exhausted run.

## Skill self-containment exception

The swarm skill's orchestrator protocol intentionally lives at the agent-definition discovery path `.zcode/agents/swarm-orchestrator.md`; this is the documented exception to skill self-containment (`.agents/rules/skills.md`) — agent definitions must live at their discovery path, and duplicating the protocol in the skill would drift.
