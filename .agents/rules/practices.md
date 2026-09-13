# Orientation, Planning, Investigation, and Making Changes

The disciplined engineering lifecycle: orient to context before starting, surface assumptions and tradeoffs before acting, investigate root causes using first-hand sources, and make the smallest surgical changes possible.

## Orientation

When starting a new project, session, task, or answering questions, always orient yourself to the project's history and current state first.

**Do not perform any work or proceed with any tasks without understanding the history and context.**

Inspect the following to orient yourself:

- **Memory Context File** — read `.agents/memory.md` (Current Activity, Completed Work Items, Decisions, Remember To Do) for the project's current state and history.
- **Plans** — glob and read `plan_docs/`, `docs/plans/`, and `docs/` for existing plans, specs, and design docs relevant to the task.
- **Uncommitted changes** — run `git status` and `git diff` to see pending work in the working directory.
- **Recent commits** — run `git log --oneline -10` to see the latest work and conventions in the current branch.

## Planning

- Always create a plan before starting any non-trivial task (e.g. >= 3 steps or >= 5 minutes of work).
- Present plans for approval before starting any non-trivial task.
- Always use TODO lists to track work to be done.
- Mark TODO items as complete when they are done.
- Present summary after completing all plans/tasks.

### Think Before Coding

Before implementing, apply these checks:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## Investigation

- Never guess at the cause of an issue.
- Always investigate the issue using first-hand sources, i.e. logs, code, output.
- Do not make or report assertions without specific details, i.e. line numbers, files, log messages, etc., to back up your claims.
- Do not determine or start implementing a solution until you have decisively found the root cause.

### Exploration discipline (act from anchors)

Pattern validated by the VS Code GPT-5.5 prompt experiment (July 2026: −8.5% tool calls, −9.3% p95 time-to-first-edit, −7.6% p95 tokens, quality neutral; `code.visualstudio.com/blogs/2026/07/06/optimizing-vscode-coding-harness-model-providers`): wandering before acting costs time and tokens without buying quality.

- Start from the most concrete anchor available — the file, symbol, failing behavior, failing command, or nearby implementation the request names. If none is named, use one targeted search or nearby read to find the anchor, then continue locally from there.
- Before the first change, gather only enough evidence to state one falsifiable local hypothesis and the cheapest check that could disconfirm it.
- Once the hypothesis, its nearby code path, and a cheap discriminating check are visible, the next action is the change itself — not more reading. A small reversible probe is a legitimate first change when confidence is incomplete.
- Searching past ~5 discovery calls with no hypothesis is drift: recover by choosing the best current hypothesis, acting on it, and reporting the gap.
- Validate in this order of preference: the cheapest behavior-scoped failing check, a narrow test of the touched slice, a narrow compile/lint/typecheck of the touched slice. Finish with at least one post-change executable validation when the environment provides one.
- Do not re-read unchanged context unless a new result makes it relevant.

## Handling Command Failures

When a CLI command fails, before retrying:

1. Read the error message and its context for hints.
2. Verify command syntax (`--help`, `Get-Help`, or tool docs).
3. Inspect usage examples and construct a corrected command from careful analysis.
4. For complex commands, break them into smaller parts and test each.

**Do not keep retrying the same command without understanding the issue.** Diagnose and fix the problem before retrying. If the command still fails after up to 3 informed attempts, search the web for the error message / docs before retrying again. Once a working command is found, document it where appropriate for future runs.

Exit-code checks: `$?` (bash success/fail) or `$LASTEXITCODE` (pwsh / native-command exit code).

## Making Changes

**Touch only what you must. Clean up only your own mess.**

- Always make the smallest most surgical change possible.
- Only make changes that are necessary to fix the issue at hand.
- Ignore areas that are not relevant to the current task.
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports, variables, and functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.
- Every changed line should trace directly to the user's request.
