# Swarm Workers

Shared instructions for every swarm worker subagent (`swarm-agent`, `swarm-implementer`, `swarm-researcher`, `swarm-verifier`, `swarm-reviewer`). Each worker definition's first line directs the worker to read this file before starting its task.

## Your conventions channel

You run with `injectAgentsMd: false` — the repo's AGENTS.md is **not** injected into your context. Your task's `Constraints` element names the governing rules files; read them. That is your only channel to repo conventions (validation, coding style) — if a repo convention matters for swarm workers, it gets copied into this file.

## Report contract

Your final report's first line is exactly one of:

- `DONE: <one-sentence outcome>`
- `BLOCKED: <reason>`

Then evidence bullets: paths read or changed, commands run with verbatim output tails, findings, sources (file path + line range, or URL). You start cold and cannot converse with the orchestrator — no questions back; blockers go in the report.

## Scope discipline

Execute exactly the delegated task, nothing more. Never expand scope, never "fix" unrelated code, never re-run verification commands with changed inputs to force a pass. Stay inside the task's named files and scope; `DONE` only when the Done-when criteria are observably met — a plan to finish does not count.

## Task input shape

Every task you receive carries four elements: **Goal** (the outcome), **Context** (exact paths, commands, excerpts), **Constraints** (governing rules files — read them), **Done when** (verifiable by you). If any element is missing, report `BLOCKED: missing <element>` rather than guessing.

## Research tools (swarm-researcher only)

Beyond the built-in WebFetch/WebSearch, you carry the Z.AI MCP tools (`web-reader`, `web-search-prime`, `zread`). Per-server tool documentation lives in [`.agents/rules/tools.md`](tools.md) — consult it when unsure of a tool's parameters. Every other worker type is MCP-free by design; do not treat MCP access as available outside the researcher role.

## Cost discipline

Subagent sessions are budgeted on wall time and tokens; the dominant waste observed is contention on a shared compilation unit and redundant build loops.

- **Build only what you own**: build your own csproj/project, not the whole solution, unless your Done-when requires the solution. Batch file edits between builds — never build after every single edit.
- **Full-suite runs are capped**: run the complete test suite at red (once, to see it fail), at green (once), and once more only if you changed shared code afterwards. Filtered runs (`--filter`) for everything in between.
- **Foreign errors get two retries, not a loop**: if compilation fails inside a file another worker owns, wait ~30 s and retry at most twice, then record it as an environmental caveat in your report and verify your own files another way. Do not poll indefinitely.
- **Don't explore a library's API surface by reflection or source-diving** when the task input or field-guide notes already carry the signatures; if they don't and exploration exceeds ~5 tool calls, report what's missing instead of burning the session on discovery.
- **Keep reports evidence-dense, not narration-dense**: verbatim command tails + file lists, nothing else.

## Message board (co-tenancy protocol)

When your task input names a board path (`.swarm/<run-id>/board/`), you are sharing the tree with concurrent workers:

- **On start**: list the board dir; read any claim covering paths you intend to touch. If a live claim (status not `done`) overlaps your scope, do not touch those paths — report `BLOCKED: claim conflict with <task-id> on <path>` unless your task input says wait-and-retry.
- **Post your claim** as `<task-id>.md`: first line `status: started|done|blocked`, then `paths:` (the files/dirs you own) and `finding:` one-liners as you go. Update `status: done` as your last action before reporting.
- **Shared files** (csproj/sln/Program.cs and similar multi-worker hot spots) require a claim even for a one-line edit; refuse-not-wait on conflict.

No board path in your task input = you are the sole writer; skip this section entirely.

## Note discipline

Field-guide notes are one line each (`swarm-state.ps1 append-note` collapses newlines, but compose single-line notes anyway): one durable finding per note, no narration.

<!-- canary: olive-siskin-5 -->
