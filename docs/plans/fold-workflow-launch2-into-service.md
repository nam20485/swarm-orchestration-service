# Fold the workflow-launch2 launcher into swarm-orchestration-service

**Status:** APPROVED and implemented — PR #20 against `development`, CI green
2026-09-15, merge owner-gated. §9 follow-ups remain open, so this stays a
top-level plan until the merge lands.
**Date:** 2026-09-15
**Supersedes:** the scratch notes that were in
`docs/plans/fold-workkspacxe-launc2-in-plan.md` (untracked; deleted 2026-09-15
once its four bullets were absorbed below and answered)
**Scope decision:** minimal transitive closure only. The `nam20485/workflow-launch2`
teardown is **plan-only** here; that repo is not touched by this change.

---

## 1. Goal

Stop launching new app repos from a joint two-repo workspace. Move the
`create-repo-agent-context.ps1` pipeline into this repo so the launcher and the
orchestration service that consumes its output live together, and reduce
`workflow-launch2` (later, separately) to a slug-indexed `plan_docs/` key-value
store.

The two halves are already one pipeline split across two repos:

```
workflow-launch2                                swarm-orchestration-service
────────────────                                ───────────────────────────
create-repo-agent-context.ps1 -Slug <slug>
  ├─ create repo from intel-agency/agent-context
  ├─ clone → ../dynamic_workflows/<name>
  ├─ copy plan_docs/<slug>/* → <clone>/plan_docs/
  ├─ placeholder + AGENTS.md identity rewrite
  ├─ cleanup-template-state / headless perms / strip model pins
  ├─ amend + push seed commit
  ├─ import-labels  ← .github/.labels.json (32 labels)
  └─ create issue "gh-issue-tracking-init"
       body: /gh-issue-tracking-init
       label: gh-issue-tracking:direct-body
                     │
                     │  webhook: issues.labeled
                     ▼
                                        filters.should_dispatch (label prefix/exact)
                                          → prompt_builder.build_orchestration_prompt
                                          → PromptQueue → AcpHost → sandbox
                                          → opencode runs the body verbatim
                                          → clone's gh-issue-tracking-init skill
                                          → plan/epic/story/task + board + labels
```

The launcher writes the labels; this service interprets them. Splitting them
across repos is the actual defect.

## 2. Verified facts (evidence for the decisions below)

| Fact | How verified |
| --- | --- |
| `intel-agency` is an Organization on plan **`enterprise`**; `nam20485` is a User on the free plan | `gh api orgs/intel-agency`, `gh api users/nam20485` |
| Template `intel-agency/agent-context` is public, `isTemplate: true`, default branch `development` | `gh repo view --json` |
| `agent-context` ships **no** `.github/.labels.json` (404) — which is why the wrapper sources labels from the *launcher's* copy | `gh api repos/.../contents/.github/.labels.json` |
| Launcher `.github/.labels.json` = 32 labels, and *contains* the dispatch vocabulary `filters.py` / `prompt_builder.py` match (`orchestration:*`, `implementation:ready\|complete`, `gh-issue-tracking:direct-body`) — it is a superset: `agent:*`, `state:*`, GitHub defaults and bare hierarchy labels are matched by nothing in `src/webhook_receiver` | label-name set vs. `grep` of `src/webhook_receiver` |
| This repo has **no** `.github/.labels.json`. The `gh-issue-tracking-init` skill's `assets/labels.json` is a *different* 19-label planning vocabulary (28 launcher labels absent, 15 skill labels absent, 3 colour conflicts on `gh-issue-tracking:direct-body`, `epic`, `story`) | `find` + JSON set diff |
| All 9 move-set scripts parse clean and are **PSScriptAnalyzer Error-clean** — they will pass this repo's `validation.ps1 -Step scan`, which already scans `scripts/` recursively | `Parser::ParseFile` + `Invoke-ScriptAnalyzer -Severity Error` |
| This repo's copies of the 5 duplicated scripts are equal-or-newer: `common-auth.ps1` / `import-labels.ps1` differ by one blank line; `create-dispatch-issue.ps1` here adds `Write-Output $issueUrl`; `update-remote-indices.ps1` here fixes two `beklow` typos and two Windows-only `Join-Path 'a\b'` calls | `diff` |
| `validation.ps1 -Step test` gates ≥85% but measures coverage only over `.agents/skills/*/scripts` — root `scripts/` is scanned, never covered | read `validation.ps1` |
| CI (`.github/workflows/ci.yml`) runs `./validation.ps1` with `-Step all`; it does **not** pin Pester, so `validation.ps1`'s `Install-RequiredModule -MinVersion 5.0.0` uses the runner's preinstalled Pester | read `ci.yml` |
| Launcher test files pin `#requires -Modules @{RequiredVersion='5.5.0'}`; this repo's 8 test files carry **no** `#requires` at all | `grep '#requires'` both repos |
| `plan_docs/` = 16 MB, 343 files, 55 slug dirs + `.INTAKE` / `.NEW` / `.wip` / `templates`, no loose files at root | `du` / `find` |
| `../dynamic_workflows/` is a sibling of **both** repos, so `-CloneParentDir '../dynamic_workflows'` resolves identically from either root | directory listing |
| Launcher `tests/*.Tests.ps1` resolve their targets as `Join-Path $PSScriptRoot '..' 'scripts' '<name>.ps1'` and build all fixtures under `[IO.Path]::GetTempPath()` — they port to a repo-root `tests/` with **zero** path edits | read all 4 test files |

## 3. Move set — the transitive closure

Nine scripts, one label asset, three test files. Nothing else in
`workflow-launch2` is reachable from `create-repo-agent-context.ps1`.

### 3.1 Scripts → `scripts/`

| File | Lines | Why it is in the closure |
| --- | --- | --- |
| `create-repo-agent-context.ps1` | 291 | Entry point. `throw`s at startup if any of the five stage scripts is missing |
| `create-repo-with-plan-docs.ps1` | 489 | Stage 1 (create → clone → seed → push). Hard-requires `repo-functions.ps1` |
| `repo-functions.ps1` | 480 | Dot-sourced helper library (`New-GitHubRepository`, `Copy-PlanDocs`, `Update-TemplatePlaceholders`, `Invoke-GitCommitAndPush`, `Wait-TemplateReady`, …) |
| `cleanup-template-state.ps1` | 206 | Stage 2 — Class-2 template-state cleanup |
| `apply-headless-permissions.ps1` | 231 | Stage 3 — `ask` → `allow` so headless dispatch cannot deadlock; `deny` preserved; coordinator agents skipped |
| `strip-model-settings.ps1` | 246 | Stage 3.5 — removes `model:` / `small_model` pins so the service's dispatch model wins |
| `trigger-gh-issue-tracking-init.ps1` | 151 | Stage 5 — creates the `gh-issue-tracking:direct-body` dispatch issue |
| `dispatch-labels.ps1` | 85 | Dot-sourced by stage 5 for `Ensure-DispatchBootstrapLabel`; **absent from this repo** |
| `logging.ps1` | 80 | Soft-required by stage 1 (`Start-RunLog` / `Write-RunLog` / `Complete-RunLog`); writes `<repo>/logs/*.jsonl` |

### 3.2 Asset → `.github/.labels.json`

Copy the launcher's 32-label file to `.github/.labels.json` (same repo-relative
position, so `Join-Path $scriptDir '..' '.github/.labels.json'` in
`create-repo-agent-context.ps1:166` keeps working unchanged). This is the
"missing major thing": it is the dispatch vocabulary this service's
`filters.py` and `prompt_builder.py` match on, it is the source stage 4 imports
into every new clone, and `agent-context` does not ship one. This repo is its
correct owner — the service that interprets the labels should hold the
canonical set.

Do **not** merge it with `.agents/skills/gh-issue-tracking-init/assets/labels.json`;
they are different vocabularies with three colour conflicts. Reconciling them is
a separate question (see §9).

### 3.3 Tests → `tests/` (new repo-root directory)

| File | Disposition |
| --- | --- |
| `cleanup-template-state.Tests.ps1` (141 L) | Move as-is, minus `#requires` |
| `create-repo-with-plan-docs.Tests.ps1` (693 L) | Move as-is, minus `#requires`. Covers `repo-functions.ps1` + DryRun integration |
| `logging.Tests.ps1` (144 L) | Move as-is, minus `#requires` |
| `create-repo-from-slug.Tests.ps1` (132 L) | **Drop** — it only reflects on the legacy wrapper's parameters and regex-matches its source. **Salvage** its final `Describe 'DryRun integration'` into a new `tests/create-repo-agent-context.Tests.ps1`, retargeted at `-PlanDocsRoot` and the new owner/visibility guard |
| `pester.config.ps1` | **Drop** — `validation.ps1` builds its own `New-PesterConfiguration`; this config carries the launcher's 55% target and `TestResults/` paths |

Repo-root `tests/` is chosen over `scripts/tests/` because the existing
`Join-Path $PSScriptRoot '..' 'scripts' …` joins then resolve correctly with no
edits.

### 3.4 Reused in place — already here, do **not** import

`import-labels.ps1`, `common-auth.ps1`, `create-dispatch-issue.ps1` (this repo's
copy is a superset). All three are resolved via `$PSScriptRoot` by the moved
scripts, so they bind to the local copies automatically.

### 3.5 Explicitly not moved

| Item | Reason |
| --- | --- |
| `create-repo-from-slug.ps1`, `trigger-project-setup.ps1`, `TestTriggerProjectSetup.ps1` | Legacy `ai-new-workflow-app-template` + `/orchestrate-dynamic-workflow project-setup` path, superseded by the agent-context wrapper. Unreachable: the wrapper always passes `-SkipProjectSetup $true` |
| `initiate-new-repo.ps1` (408 L), `init-template-repo.ps1`, `create-milestones.ps1` | Different template (`nam20485/ai-new-app-template`), different flow, 2025 milestone dates. This repo already has a `create-milestones.ps1` inside the `gh-issue-tracking-init` skill |
| `create-all-repo-plans.ps1` | **Broken**: uses bash `\` line continuations, so every `\` is passed as a literal argument. Not worth porting as-is |
| `delete-gh-repos.ps1`, `validate-toolset.ps1`, `launch-claude-code.ps1`, `convert_mhtml.py` | Not in the closure; unrelated utilities |
| `query.ps1`, `update-remote-indices.ps1`, `create-dispatch-issue.ps1`, `import-labels.ps1`, `common-auth.ps1` | Already here, newer |
| `.github/workflows/test-scripts.yml` | Superseded — the suite runs through `validation.ps1` per §5.4 (owner decision) |
| `.claude/`, `.gemini/`, `.kilo/`, `.kilocode/`, `.qwen/`, `.vscode/`, `.devcontainer/`, `CLAUDE.md`, `local_ai_instruction_modules/` extras, `docs/` research dumps, `logs/`, `TestResults/`, `.dirac-cache/` | Not launcher-pipeline support. `.kilo*` are mostly `node_modules`; `logs/`, `TestResults/`, `.qwen/`, `.dirac-cache/` are gitignored artifacts |

Two launcher docs *are* pipeline support and should move (§5.6).

## 4. Code changes the fold forces

### 4.1 `-PlanDocsRoot` — make the source root explicit

`create-repo-agent-context.ps1:161` sets `$PlanDocsDir = "./plan_docs/$Slug"`.
That is **CWD-relative**, and `Copy-PlanDocs` (`repo-functions.ps1`) resolves it
with `Test-Path -LiteralPath` and `throw`s `Plan docs directory not found`.
Today CWD must be the `workflow-launch2` root. After the move CWD is this repo,
which has no `plan_docs/` — so it hard-fails before the slug logic matters.

Change (keeps the `plan_docs/ + -Slug` model, makes only the *root* explicit):

```powershell
[Parameter()]
[ValidateNotNullOrEmpty()]
[string]$PlanDocsRoot = (Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs'),
...
$PlanDocsDir = Join-Path $PlanDocsRoot $Slug
```

plus an up-front `Test-Path -LiteralPath $PlanDocsDir` guard whose message names
the resolved root, the slug, and `-PlanDocsRoot` as the override.

Same treatment for `$CloneParentDir = '../dynamic_workflows'` →
`Join-Path $PSScriptRoot '..' '..' 'dynamic_workflows'`. It happens to resolve
identically from either sibling root today, but leaving one path CWD-relative
next to one script-relative is the inconsistency that caused this bug. After
both, the script is fully CWD-independent — matching how it already resolves
every stage script and the labels file via `$PSScriptRoot`.

The destination side (`plan_docs/` **inside the clone**, committed by the seed
commit) is unaffected — `Copy-PlanDocs` writes `Join-Path $RepoRoot 'plan_docs'`.

### 4.2 Owner/visibility guard

Owner-declared rule: **bail unless `($Owner -eq 'intel-agency' -or $Visibility -eq 'public')`**
— public under any owner, private only under `intel-agency`. Rationale confirmed
live: `intel-agency` is on the `enterprise` plan; `nam20485` is free-tier, where
private repos get no Actions minutes, so a private clone's dispatch workflows
could never run.

Add to `repo-functions.ps1` (shared, testable):

```powershell
function Test-OwnerVisibilityPolicy {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Owner, [Parameter(Mandatory)][string]$Visibility)
    return ($Owner -eq 'intel-agency' -or $Visibility -eq 'public')
}
```

Call it from `create-repo-agent-context.ps1` immediately after parameter
validation — before any `gh` call — and from the `Create` parameter set of
`create-repo-with-plan-docs.ps1` (it is independently invocable and carries its
own `-Owner` / `-Visibility`). Not applicable to the `ReplaceOnly` set.
Bails regardless of `-DryRun`, so a dry run surfaces the same failure.

Message must state the predicate and the reason, e.g.:

> `Invalid owner/visibility combination: 'nam20485/private'. Private repos are only
> supported under the 'intel-agency' owner (Enterprise Cloud Actions minutes);
> free-tier private repos get no minutes, so the clone's dispatch workflows could
> never run. Use -Owner intel-agency, or -Visibility public.`

Also fix the live doc/code mismatch while here: `create-repo-agent-context.ps1`'s
`-Owner` **default is `nam20485`** while its own comment-based help and the
launcher's `scripts/README.md` both say `intel-agency`. Set the default to
`intel-agency` so the documented behaviour is the real behaviour.

### 4.3 The legacy project-setup trigger block

`create-repo-with-plan-docs.ps1:443-465` invokes `trigger-project-setup.ps1`
when `-TriggerProjectSetup` is true and `-SkipProjectSetup` is absent. That
script is **not** in the move set. Left as-is, a direct invocation would
`Test-Path`-miss and silently `Write-Warning … skipping workflow trigger` — a
quiet behaviour regression.

**Recommended:** delete the block and the `-TriggerProjectSetup` /
`-SkipProjectSetup` parameters, since the only caller (the agent-context
wrapper) always passed `-SkipProjectSetup $true` and the legacy
`ai-new-workflow-app-template` flow is being deprecated with
`workflow-launch2`. **Alternative if you prefer a pure move:** keep the block
and also move `trigger-project-setup.ps1`. Flagged because it is the one place
this change edits logic rather than relocating it.

## 5. Supporting changes in this repo

1. **`.gitignore`** — add `logs/` (written by `logging.ps1` →
   `Start-RunLog -LogDir (Join-Path $PSScriptRoot '..' 'logs')`). `TestResults/`
   and `coverage.xml` are already ignored. The launcher's `run-plans/` entry is
   not needed — no script references it.
2. **`validation.ps1`** — add `(Join-Path $repoRoot 'tests')` to `$testPaths` in
   `Step-Test`. Do **not** add `scripts/` to `$coveragePaths`: the ≥85% gate
   stays measured over the same three `.agents/skills/*/scripts` dirs, and the
   moved scripts join the 8 existing root scripts that are PSScriptAnalyzer-scanned
   but coverage-unmeasured. `Step-Scan` already covers `scripts/` — no change.
3. **Drop the `#requires -Modules @{RequiredVersion='5.5.0'}` lines** from the
   three moved test files. This repo's 8 test files carry no `#requires`, and CI
   does not pin Pester to 5.5.0 — an exact `RequiredVersion` would fail the file
   on a runner shipping 5.6+. Keep `#requires -Version 7.0`.
4. **`.agents/rules/scripts.md`** — add the nine moved scripts to the inventory
   table (the repo's convention; there is no `scripts/README.md` here), plus a
   short "New-app launch pipeline" section carrying the stage order, the
   `-PlanDocsRoot` contract, the owner/visibility policy, and the prerequisites
   (§6). Fold in the substance of the launcher's `scripts/README.md`
   "agent-context clone seeding" narrative.
5. **`AGENTS.md`** — extend the *Repository Scripts* brief to mention the launch
   pipeline (two-part brief per the AGENTS.md convention; link, don't inline).
6. **Move two launcher docs that support the pipeline:**
   - `docs/wsl-ssh-agent-setup-guide.md` → `docs/` — `Invoke-GitClone` clones via
     `git@github.com:`, so an SSH agent is a hard prerequisite on WSL/Linux.
   - `docs/orchestration-cycle-label-trigger-options.md` → `docs/plans/completed/`
     — the 2026-07-21 design analysis for the label-driven cycle this service now
     implements (its Axis A1 completion label shipped as
     `gh-issue-tracking:init-success`). Historical design record; would otherwise
     die with the teardown.
   Both land under markdownlint's `docs/*.md` glob except the `completed/` one
   (`docs/*.md` does not recurse), so the SSH guide must lint clean.
7. **`docs/plans/README.md`** — index this plan at top level (status PROPOSED);
   move to `completed/` in the change that lands it.
8. **`.agents/memory.md`** — new Current Activity entry for the fold.
9. **`swarm-orchestration-service.code-workspace`** — the uncommitted change
   adding `../workflow-launch2` as a second folder stays: `plan_docs/` still
   lives there, so the editor needs both roots. Commit it as part of this change.

## 6. Prerequisites the moved pipeline needs at run time

Document these in `.agents/rules/scripts.md`; they are not enforced by the
scripts except where noted:

- `gh` authenticated with `repo`, `workflow`, `admin:org` (secrets/variables) and
  SSH access to `git@github.com:` — `Invoke-GitClone` uses SSH, not HTTPS.
- `GEMINI_API_KEY` present in the environment — `New-RepoSecret` reads the secret
  body from the env var of the same name and `throw`s if unset.
- `../workflow-launch2/plan_docs/<slug>/` present — or `-PlanDocsRoot` pointed
  elsewhere (§4.1).
- `code-insiders` on PATH, only for `-LaunchEditor`.
- Template `intel-agency/agent-context` reachable.

## 7. Verification

1. `./validation.ps1 -Step build` — markdownlint over the new/edited `docs/*.md`,
   `.agents/rules/scripts.md`, `AGENTS.md`; relative-link check on README/AGENTS.
2. `./validation.ps1 -Step scan` — PSScriptAnalyzer Error severity over
   `scripts/` (now 17 scripts). Pre-verified clean for all 9 arrivals; must stay
   clean after the §4 edits. Plus gitleaks over the new `.github/.labels.json`.
3. `./validation.ps1 -Step test` — the 3 moved suites + the salvaged
   `create-repo-agent-context.Tests.ps1` must pass, and the ≥85% coverage gate
   must be unchanged (same denominator as before).
4. New targeted tests to add in `tests/create-repo-agent-context.Tests.ps1`:
   - `Test-OwnerVisibilityPolicy` truth table — `intel-agency/private` ✔,
     `intel-agency/public` ✔, `nam20485/public` ✔, `nam20485/private` ✘.
   - Entry point bails with the reason-bearing message on `nam20485/private`,
     **and creates no repo** (assert before any `gh` call).
   - `-PlanDocsRoot` default resolves to `<repo>/../workflow-launch2/plan_docs`;
     `-Slug x` maps to `<root>/x`; a missing slug dir throws naming the root and
     the override.
   - DryRun integration through `create-repo-with-plan-docs.ps1` (salvaged test).
5. `./validation.ps1` (`-Step all`) — the full gate CI runs, including dotnet,
   python and e2e branches.
6. **End-to-end dry run** (no mutation): from this repo root,
   `./scripts/create-repo-agent-context.ps1 -Slug '<existing-slug>' -DryRun -Yes`
   must resolve `plan_docs/<slug>` in `workflow-launch2`, walk all five stages,
   and report the labels file — proving CWD-independence and the closure.
7. **One real launch** against a throwaway slug, then delete the repo
   (`delete_repo` scope needed; the Phase 4 demo repo
   `nam20485/swarm-orch-demo-scratch` is the precedent for retaining evidence
   instead). Confirm: seed commit contains the plan docs and the stripped model
   pins; all 32 labels imported; dispatch issue created with
   `gh-issue-tracking:direct-body`; this service's listener accepts the
   `issues.labeled` delivery and reaches `agent_finished`.

## 8. Delivery shape

Single PR on a `dev/fold-launcher` branch off `development`, milestone
`maintenance`, per `.agents/rules/source-control.md` (`/safe-commit` before
committing). Suggested commit split:

1. move the 9 scripts + `.github/.labels.json` verbatim (no logic changes)
2. move the 3 test suites, drop `#requires`, add `tests/create-repo-agent-context.Tests.ps1`
3. `-PlanDocsRoot` + CWD-independence (§4.1)
4. owner/visibility guard + `-Owner` default fix (§4.2)
5. legacy trigger-block removal (§4.3)
6. `.gitignore`, `validation.ps1`, docs, memory, workspace file (§5)

Commit 1 being a verbatim move keeps `git log --follow` usable and makes the
behavioural commits reviewable in isolation.

## 9. Follow-ups (not in this change)

- **`workflow-launch2` teardown — plan only.** Reduce it to `plan_docs/` + a
  README declaring it a slug-indexed, directory-valued key-value store. Deletes
  `scripts/`, `tests/`, `.github/` (except what `plan_docs` needs), the agent
  config dirs, `docs/`, `local_ai_instruction_modules/`, `CLAUDE.md`. Needs its
  own change in that repo, plus a decision on whether `.INTAKE` / `.NEW` /
  `.wip` / `templates` count as slugs or as index metadata (they are not slugs —
  `.INTAKE` holds raw conversation dumps awaiting promotion, `templates/` holds
  the four app-plan authoring templates).
- **Label vocabulary reconciliation.** 32-label orchestration set vs. the
  `gh-issue-tracking-init` skill's 19-label planning set, with colour conflicts
  on `gh-issue-tracking:direct-body`, `epic`, `story`. Now that both live in this
  repo, decide whether they merge into one canonical file.
- **App-plan authoring side.** `plan_docs/templates/` +
  `docs/agent-creation-instructions.md` + `docs/new-ai-app-creation-templates/`
  are the "how to write a slug" half. They stay with `plan_docs` under the
  teardown plan; revisit if authoring should also fold in here.
- **Intake → slug promotion flow** (`plan_docs/.INTAKE` → a promoted slug dir)
  has no owner after the teardown. Decide whether it becomes a skill here.

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| A closure dependency was missed and surfaces only on a real launch | §7.6 DryRun walk plus §7.7 real launch before the PR merges; the startup `throw`-if-missing checks in the wrapper fail loudly, not silently |
| `#requires` removal changes Pester behaviour | This repo's 8 existing suites already run with no `#requires` under the same `validation.ps1` |
| Adding `tests/` to `$testPaths` shifts the coverage denominator | It cannot — `$coveragePaths` is untouched and lists three explicit directories |
| `logging.ps1`'s `Set-StrictMode -Version Latest` at dot-source time leaks into the caller session | Pre-existing behaviour, unchanged by the move; only `create-repo-with-plan-docs.ps1` dot-sources it |
| The teardown deletes launcher content someone still needs | Teardown is plan-only here and gated behind §9's open decisions |
