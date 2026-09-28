# Agent-Instructions Remote Canonical Modules

Index files for workflow assignments and dynamic workflows from the remote canonical repo **`nam20485/agent-instructions`** (branch `main`). These local index files are the lookup tables the `/commands` system resolves against (`/orchestrate-dynamic-workflow`, `/orchestrate-project-setup`, etc.) and are kept in sync with the remote by `scripts/update-remote-indices.ps1`.

- Workflow assignments index: [`local_ai_instruction_modules/ai-workflow-assignments.md`](../../local_ai_instruction_modules/ai-workflow-assignments.md)
- Dynamic workflows index: [`local_ai_instruction_modules/ai-dynamic-workflows.md`](../../local_ai_instruction_modules/ai-dynamic-workflows.md)

## What the remote repo is

`nam20485/agent-instructions` is the canonical source of:

- **Workflow assignments** — one shortId per `.md` in `ai_instruction_modules/ai-workflow-assignments/` (e.g. `init-existing-repository`, `create-app-plan`, `pr-review-comments`, `orchestrate-dynamic-workflow`).
- **Dynamic workflows** — one shortId per `.md` in `ai_instruction_modules/ai-workflow-assignments/dynamic-workflows/` (e.g. `project-setup`, `create-epics-for-phase`, `implement-epic`).

Each index entry lists a shortId, the GitHub UI URL, the raw URL, and the canonical file path inside the remote repo.

## When to use it

- When a workflow needs to resolve a shortId to its canonical instructions, the `/commands` read the corresponding local index file and then fetch the remote `.md` via its raw URL.
- The local index files are the authoritative **directory** of available shortIds; the remote repo is the authoritative **content**.

## Where things live (do not relocate)

Both index files stay at the repo-root `local_ai_instruction_modules/` path. That path is hard-coded by:

- `scripts/update-remote-indices.ps1:123-124` (`Join-Path $repoRoot 'local_ai_instruction_modules' ...`), and
- the `/commands` that consume them.

**Do not move these two files** into `.agents/` without simultaneously updating both consumers.

## How to refresh the indices

```bash
pwsh ./scripts/update-remote-indices.ps1
# Defaults: -Owner nam20485 -Repo agent-instructions -Branch main
```

The script fetches the remote directory listings, rebuilds both index files, and writes only if the content changed.

<!-- canary: mauve-marten-7 -->
