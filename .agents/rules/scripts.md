# Repository Scripts

Automation scripts under the repo-root [`scripts/`](../../scripts/) directory — GitHub CLI helpers for authentication, label synchronization, PR review-thread management, permission verification, orchestrator dispatch, and remote-instruction-module index regeneration, plus the **new-app launch pipeline** (`create-repo-agent-context.ps1` + its stage scripts) that seeds a fresh clone of the `nam20485/swarm-context` parent template from a `plan_docs/` slug and files the dispatch issue this service listens for. Most scripts accept a `-DryRun` switch so actions can be previewed without mutation.

The two most-used: `query.ps1` (canonical PR review-thread list/reply/resolve via GraphQL — do not rewrite ad hoc) and `import-labels.ps1` (idempotent label sync from a JSON export).

## Script inventory

Built from each script's header comments and `param()` block. **Read the file header and `param()` block in the script itself for authoritative parameter documentation, examples, and `NOTES`** — the table below is a quick-reference only.

| Script | Purpose | Key parameters |
| --- | --- | --- |
| `common-auth.ps1` | Dot-sourceable `gh` auth bootstrap (`Initialize-GitHubAuth`). Verifies `gh` is on PATH and triggers `gh auth login` if unauthenticated. | `-DryRun` |
| `gh-auth.ps1` | `gh` auth bootstrap with non-interactive PAT-stdin support (`gh auth login --with-token`). Falls back to interactive login. | `-DryRun`, `-Token <pat>` |
| `import-labels.ps1` | Syncs labels from a JSON export into a target repo: creates missing labels, updates color/description when they differ, optionally deletes labels not in the source. | `-Repo <owner/repo>`, `-LabelsFile ./.labels.json`, `-DryRun`, `-DeleteMissing` |
| `query.ps1` | PR review-thread management via GraphQL — list unresolved threads, post a reply to each, then resolve. **Canonical tool** for resolving PR review comments; do not write ad-hoc Python/shell for this. | `-Owner`, `-Repo`, `-PullRequestNumber`, `-ThreadId`, `-Path <wildcard>`, `-BodyContains`, `-Interactive`, `-AutoResolve`, `-NoResolve`, `-DryRun`, `-VerboseLogging`, `-ReplyEach "<msg>"` |
| `create-dispatch-issue.ps1` | Creates a GitHub issue on a target repo, defaulting the title to `orchestrate-dynamic-workflow` so it triggers the orchestrator match clause. Title/body can be overridden for arbitrary issue creation. | `-Repo <owner/repo>`, `-Title`, `-Body <text>`, `-Labels[]`, `-Project`, `-Milestone`, `-Template`, `-Assignee[]`, `-DryRun` |
| `test-github-permissions.ps1` | End-to-end verifier: `gh` auth status, scopes (`user:email`, `repo`, `project`), repo create/delete, project create, label/milestone/branch-permission workflow. Optional auto-fix for missing scopes. | `-Owner <user>`, `-TestRepoName`, `-TestProjectName`, `-Cleanup`, `-AutoFixAuth` |
| `update-remote-indices.ps1` | Regenerates the two `local_ai_instruction_modules/` index files from the remote canonical `nam20485/agent-instructions` repo listing (only writes if content changed). | `-Owner <owner>`, `-Repo <repo>`, `-Branch <branch>` |
| `create-repo-agent-context.ps1` | **ENTRY POINT**: launches a new app repo from a `plan_docs` slug — creates it from the `nam20485/swarm-context` parent template, clones, seeds the slug's plan docs, runs the cleanup / headless-permission / model-pin stages, amends the seed commit, imports labels, files the `/gh-issue-tracking-init` dispatch issue. | `-Slug`, `-PlanDocsRoot`, `-Owner`, `-Visibility`, `-Count`, `-Yes`, `-LaunchEditor`, `-TriggerHierarchyInit`, `-DryRun`, `-Help` |
| `create-repo-with-plan-docs.ps1` | Stage 1: create `<Owner>/<RepoName>-<suffix>` from a template, clone, copy plan docs into the clone's `plan_docs/`, replace placeholders, rewrite `AGENTS.md` identity, commit and push with template-race rebase retry. Has a `ReplaceOnly` parameter set for re-running replacement on an existing checkout. | `-RepoName`, `-Owner`, `-PlanDocsDir`, `-CloneParentDir`, `-Visibility`, `-Count`, `-TemplateRepoName`, `-TemplateOwner`, `-ExistingRepoRoot`, `-Yes`, `-DryRun` |
| `repo-functions.ps1` | Dot-sourceable helper library for stage 1 (no top-level execution): suffix/name generation, `gh repo create`, clone, plan-docs copy, placeholder replace + assert, secrets/variables, commit-and-push with rebase detection, template-readiness poll, `Test-OwnerVisibilityPolicy`. | functions only |
| `cleanup-template-state.ps1` | Stage 2: Class-2 cleanup of a fresh clone — resets `.agents/memory.md` to a skeleton, clears `docs/plans/` `.completed` and `.deferred`, removes the leaked `run-issues-review` subtree and named template-self plans. Idempotent. | `-RepoRoot`, `-DryRun` |
| `apply-headless-permissions.ps1` | Stage 3: rewrite the clone's opencode permissions so a headless dispatch cannot deadlock on an unanswerable ask — `ask` becomes `allow` in `.opencode/agents/*.md` frontmatter (explicit `deny` preserved, coordinator agents skipped) and the project-config permission object becomes `"allow"`. Idempotent. | `-RepoRoot`, `-DryRun` |
| `strip-model-settings.ps1` | Stage 3.5: remove every `model:` pin from agent frontmatter and the `model` / `small_model` keys from `.opencode/opencode.json(c)` so this service's dispatch and runtime model selection prevails. Idempotent. | `-RepoRoot`, `-DryRun` |
| `trigger-gh-issue-tracking-init.ps1` | Stage 5: file the dispatch issue (title and body `/gh-issue-tracking-init`) labelled `gh-issue-tracking:direct-body` so this service's listener runs the body verbatim; bootstraps each label from a labels file first. | `-Repo`, `-Labels`, `-BootstrapLabelsFile`, `-DryRun` |
| `dispatch-labels.ps1` | Dot-sourceable label-bootstrap helpers (`Get-BootstrapLabelDefinition`, `Ensure-DispatchBootstrapLabel`) for the dispatch triggers. Functions only — never add top-level statements. | functions only |
| `logging.ps1` | Dot-sourceable JSONL run logging (`Start-RunLog` / `Write-RunLog` / `Complete-RunLog`), one timestamped file per run under the gitignored `logs/`. | `-LogDir`, `-RunName` (on `Start-RunLog`) |

## New-app launch pipeline

`create-repo-agent-context.ps1 -Slug <slug>` is the whole pipeline; it shells out to the stage scripts in this order and stops on the first failure (each stage is separately invocable, and stages 2–3.5 are idempotent):

- **Stage 1** — `create-repo-with-plan-docs.ps1`: create the repo from the template, clone it, copy the slug's plan docs in, rewrite placeholders and the `AGENTS.md` identity, commit and push.
- **Stage 2** — `cleanup-template-state.ps1`: reset the clone's template memory/plan state.
- **Stage 3** — `apply-headless-permissions.ps1`: relax `ask` → `allow` so a headless dispatch never blocks.
- **Stage 3.5** — `strip-model-settings.ps1`: drop model pins so this service chooses the model.
- **Amend** the seed commit, folding stages 2–3.5 into the clone's first commit, then `git push --force-with-lease origin HEAD:main` so the cleanup reaches the remote — stage 1 already pushed the pre-cleanup seed commit.
- **Stage 4** — `import-labels.ps1`: sync `.github/.labels.json` into the new repo, so every dispatch label exists before the trigger.
- **Stage 5** — `trigger-gh-issue-tracking-init.ps1`: file the `gh-issue-tracking:direct-body` issue that this service's webhook turns into an agent session.

**plan_docs contract.** `-PlanDocsRoot` defaults to `(Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs')` — the sibling `workflow-launch2` checkout, which stays the slug-indexed store after the fold; `plan_docs/` was deliberately not moved into this repo. The source directory is `<PlanDocsRoot>/<Slug>`, and a missing slug throws up front, naming the resolved root and `-PlanDocsRoot` as the override. Everything else (stage scripts, the labels file, `-CloneParentDir` → the sibling `dynamic_workflows/`) resolves from `$PSScriptRoot` too, so the pipeline is CWD-independent — no need to invoke it from a launcher root. The destination `plan_docs/` **inside the clone**, committed by the seed commit, is a different thing and is unaffected.

**Owner/visibility policy.** `Test-OwnerVisibilityPolicy` (in `repo-functions.ps1`) bails unless `$Owner -eq 'intel-agency' -or $Visibility -eq 'public'` — public under any owner, private only under `intel-agency`. Both entry points call it before any `gh` call and it fires under `-DryRun` too, so a dry run surfaces the same failure. Why: `intel-agency` is an Organization on the enterprise plan, while `nam20485` is free-tier, where private repos get no Actions minutes — a private clone's dispatch workflows could never run.

**`.github/.labels.json`.** The 32-label file is the canonical **dispatch** vocabulary: it *contains* the labels `src/webhook_receiver/filters.py` and `prompt_builder.py` match on (`orchestration:*`, `implementation:ready|complete`, `gh-issue-tracking:direct-body`) but is a superset — it also ships GitHub defaults and hierarchy labels matched by nothing in this repo (`agent:*`, `state:*`, `epic`, `story`, `bug`, …). Stage 4 imports it into every clone because the `intel-agency/agent-context` template ships no labels file, so the pipeline sources it from the launching repo — which is now this one. It is deliberately **not** merged with `.agents/skills/gh-issue-tracking-init/assets/labels.json`: that is a 19-label *planning* vocabulary, 28 labels of one are absent from the other and 15 back the other way, with 3 colour conflicts (`gh-issue-tracking:direct-body`, `epic`, `story`).

**Runtime prerequisites** (enforced by the scripts only where noted):

- `gh` authenticated with `repo`, `workflow` and `admin:org` scopes (the latter for secrets/variables).
- A live SSH agent — `Invoke-GitClone` clones over `git@github.com:`, not HTTPS (setup: [`docs/wsl-ssh-agent-setup-guide.md`](../../docs/wsl-ssh-agent-setup-guide.md)).
- `GEMINI_API_KEY` present in the environment for real launches — `New-RepoSecret` reads the secret body from the env var of that name and throws if it is unset; under `-DryRun` an unset var only warns.
- `code-insiders` on PATH, only when `-LaunchEditor` is passed.
- The `nam20485/swarm-context` parent template reachable (GitHub template route; cross-owner stamp with nam20485's PAT).

**Tests** live in the repo-root [`tests/`](../../tests/) directory (four suites, including `create-repo-agent-context.Tests.ps1` for the entry point). They are wired into `validation.ps1`'s `Step-Test` `$testPaths` but deliberately **not** into its `$coveragePaths`, so the ≥85% gate keeps measuring only the three `.agents/skills/*/scripts` directories and `scripts/` stays PSScriptAnalyzer-scanned, coverage-unmeasured.

## Generating a labels export

`import-labels.ps1` consumes a JSON file produced by:

```bash
gh api repos/{owner}/{repo}/labels --paginate > .labels.json
```

## Common conventions

- `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'` are active in the auth-aware scripts; treat missing properties via `PSObject.Properties` (not direct member access).
- Auth-aware scripts dot-source `common-auth.ps1` (or `gh-auth.ps1`) if present and call `Initialize-GitHubAuth` before doing any API work.
- `-Repo` parameters validate `^[^/]+/[^/]+$` (`owner/repo` form).

## Note on `scripts/` vs the gh-issue-tracking skill's `scripts/`

The `.agents/skills/gh-issue-tracking-init/scripts/` directory is a **separate, self-contained** set of operation scripts (vendored copies of the generic helpers plus skill-specific ops). It is documented in that skill's own [`scripts/README.md`](../skills/gh-issue-tracking-init/scripts/README.md), not here.

## Note on `tmp-issue-body-project-setup.txt`

`scripts/tmp-issue-body-project-setup.txt` is a kept scratch file — a staged draft of the `-Body` payload for a `create-dispatch-issue.ps1` project-setup dispatch. It is **not** a script and is **not** consumed by anything (`create-dispatch-issue.ps1` takes `-Body` as a string argument, not a file); it is retained as a reference example of a dispatch body.
