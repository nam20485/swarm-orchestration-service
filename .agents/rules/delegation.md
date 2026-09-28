# Delegation & Orchestration

## Delegation

- Delegate work to the appropriate subagent type when possible.
- Prefer to delegate work if you are the top-level agent, esp. if your agent type is not relevant to the current task.
- Delegate to parallel agents to speed up work and reduce implementation time.

## Structuring Task Inputs

A delegate starts cold — it cannot see your session — so the task description must carry everything it needs. **Structured context matters more than prompting tricks.** Give every non-trivial task input four elements:

1. **Goal** — what to build or change: fix a bug, implement an endpoint, refactor a module.
2. **Context** — the relevant files, error messages, documentation, or examples: which files, functions, or modules are involved.
3. **Constraints** — the engineering requirements to follow: coding standards, architectural rules, security requirements, dependency limitations. Name the governing rules file(s) under `.agents/rules/` instead of restating them.
4. **Done when** — how completion is evaluated: tests passing, behavior changing as expected, the bug no longer reproducing. Write these so the delegate can verify done-ness independently (executor side: [coding-style.md](coding-style.md) — Goal-Driven Execution).

This structure reduces the delegate's guesswork and makes its changes more consistent and easier to review.

Source: [Z.AI DevPack best practices — "Structure Task Inputs"](https://docs.z.ai/devpack/resources/best-practice#2-structure-task-inputs-context-matters-more-than-prompting-tricks).

## Orchestration

Use orchestration agents to **decompose and delegate** work instead of implementing it all yourself. Pick the **smallest layer** that fits the scope — do not spawn a higher layer for work a lower one (or you directly) can handle.

- `orchestrator` — top-level coordinator for multi-step, multi-agent tasks. Breaks the work into a dependency graph and dispatches units to specialists (`planner`, `developer`, `code-reviewer`, `qa-tester`, `researcher`) in parallel batches. Use as the default for non-trivial, multi-part work.
- `team-lead` — owns a **single workstream** (one feature/epic/fix) end-to-end: reviews the plan, assigns specialists, and enforces the definition of done. Use when the work fits within one accountable owner.
- `team-orchestrator` — runs a **program of multiple parallel workstreams** by delegating each to a `team-lead` and managing cross-team dependencies. Use only for efforts too large for one `team-lead`; otherwise delegate straight to a `team-lead`.

<!-- canary: cerise-jay-17 -->
