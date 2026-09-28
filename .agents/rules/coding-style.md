# Coding Style

**ALWAYS load and apply these guidelines whenever making or planning code changes.**

## Default scripting language: cross-platform PowerShell

**Write all scripts in cross-platform PowerShell (PowerShell 7+, `pwsh`) unless a specific task requires otherwise.**

Cross-platform PowerShell runs identically on Linux, macOS, and Windows, so a single script works across every contributor's machine and every CI target. This is the default for repo-root scripts, CI/CD steps, and skill scripts alike. Reach for another language only when the task demands it (e.g. a tool's only SDK is Python/Node, or a skill's `compatibility` frontmatter already pins a different runtime) — and note the exception where the script lives.

This pairs with the repo's existing PowerShell conventions: `throw` for fatal errors (not `Write-Error` + `exit 1`, since scripts set `$ErrorActionPreference = 'Stop'`), comma-guard (`return ,$value`) when returning arrays, and `PSObject.Properties` null-guards under `Set-StrictMode`.

## Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

The test: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals before implementing:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan with explicit verification:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

<!-- canary: umber-fox-21 -->
