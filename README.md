# agent-context

This repository is the GitHub **template repo** for `intel-agency`: the substrate from which
each downstream instance is cloned to house a unique application plan and develop it. Any
other repo name is a clone instance seeded from this one.

## Prerequisites

- **PowerShell 7+** (`pwsh`) — all scripts in this repo are written in cross-platform
  PowerShell.
- **GitHub CLI** (`gh`) — authenticated with `repo`, `project`, and `user:email` scopes.
  Verify with:

  ```sh
  gh auth status
  ```

- **Node.js** (optional) — only needed to run `markdownlint-cli2` for Markdown linting.

## Getting started

1. Create a new repository from this template (or clone it).
2. Read [`AGENTS.md`](AGENTS.md) — the operating manual for AI agents working in this repo.
3. Consult [`.agents/memory.md`](.agents/memory.md) for project history and current state.

## Configuration

Secrets are referenced as `{env:VAR}` patterns in [`.opencode/opencode.jsonc`](.opencode/opencode.jsonc)
and are never committed to the repository.

## Repository layout

| Path | Description |
|---|---|
| `AGENTS.md` | Operating manual for AI agents (coding guidelines, validation, source control) |
| `.agents/memory.md` | Durable project context: current activity, completed work, decisions |
| `.agents/rules/` | Coding conventions, tool usage, validation, and practices (one file per subject) |
| `.agents/skills/` | Agent Skills (`swarm` goal-loop swarm, `swarm-plan` interactive planning frontend, `gh-issue-tracking-init`, `update-powershell-standard`) |
| `docs/` | Reference documentation and plans |
| `scripts/` | GitHub CLI helpers: auth, label sync, PR review-thread management, index refresh |
| `src/SwarmSandbox/` | Aspire + Docker sandbox-provisioning service (5 .NET 10 projects + sandbox image definition); see [`src/SwarmSandbox/ARCHITECTURE.md`](src/SwarmSandbox/ARCHITECTURE.md) |
| `local_ai_instruction_modules/` | Workflow assignment and dynamic workflow lookup tables |
| `.opencode/` | OpenCode agent definitions and runtime configuration |

## Running the tests

The Pester test suite covers the `gh-issue-tracking-init` skill scripts:

```pwsh
Invoke-Pester -Path .agents/skills/gh-issue-tracking-init/scripts/tests -Output Detailed
```

Expected result: 101 tests passing across three test files (`GhIssueTracking`,
`SetProjectFields`, `AssertNoSecrets`).

## Linting

Markdown linting uses `markdownlint-cli2` with configuration in [`.markdownlint.json`](.markdownlint.json).
Scope linting to changed files to avoid known pre-existing violations in
`local_ai_instruction_modules/`:

```sh
markdownlint-cli2 README.md .agents/memory.md
```

## Contributing

- Create a new branch for each change using the form `<prefix>/<name>` (e.g. `dev/new-feature`).
- Run `/safe-commit` before committing to scan for uncommitted secrets.
- Pull requests must have a milestone and project set. See
  [`.agents/rules/source-control.md`](.agents/rules/source-control.md) for full details.

## Where to look next

- [`AGENTS.md`](AGENTS.md) — start here for agent operating instructions.
- [`.agents/memory.md`](.agents/memory.md) — project history and decisions.
- [`.agents/rules/`](.agents/rules/) — detailed conventions for each subject area.
