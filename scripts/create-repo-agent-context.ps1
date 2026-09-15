#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Create a new `agent-context`-seeded repo with Class-2 cleanup and
    `/gh-issue-tracking-init` hierarchy dispatch.

.DESCRIPTION
    Thin wrapper over the existing `create-repo-with-plan-docs.ps1` + the new
    `cleanup-template-state.ps1` and `trigger-gh-issue-tracking-init.ps1`.

    It accepts the core launch parameters (Slug, Owner, Visibility, Count,
    Yes) plus agent-context-specific ones (-TriggerHierarchyInit, default
    $true).

    Owner/visibility policy: a private repo is only supported under `-Owner
    intel-agency` (an Organization on the Enterprise plan); every other owner
    must be `-Visibility public`. Enforced by `Test-OwnerVisibilityPolicy`
    (from `repo-functions.ps1`) before any `gh` call, and it bails under
    `-DryRun` too, so a dry run surfaces the same failure as a real launch.

    Pipeline order per repo:
      1. create-repo-with-plan-docs.ps1 <params>
      2. cleanup-template-state.ps1 -RepoRoot <clonePath>
      3. apply-headless-permissions.ps1 -RepoRoot <clonePath>
         (relax template `ask` -> `allow` so headless orchestrator dispatches
           never block on an unanswerable permission ask; preserves `deny`)
       3.5. strip-model-settings.ps1 -RepoRoot <clonePath>
          (remove every agent `model:` pin + project-config `model` /
            `small_model` keys so the orchestrator-service runtime/dispatch
            model selection prevails; the template's per-tier models — glm-5.3 /
            glm-5.3-flash — are kept in the template for
            non-orchestrator interactive clones)
      4. import-labels.ps1 -Repo "$Owner/$RepoName"
          -LabelsFile <this repo>/.github/.labels.json
      5. trigger-gh-issue-tracking-init.ps1 -Repo "$Owner/$RepoName"
          -BootstrapLabelsFile <this repo>/.github/.labels.json

    Every path is resolved from this script's own directory, never the current
    working directory: plan docs are read from `-PlanDocsRoot` (default: the
    sibling `workflow-launch2` checkout, which still holds the slug-indexed
    `plan_docs/` store) and clones land in the sibling `dynamic_workflows/`.

.PARAMETER Slug
    Base app-plan slug (prefix). A random suffix is appended to form the final
    repo name.

.PARAMETER PlanDocsRoot
    Root of the plan-docs store; the source directory is '<PlanDocsRoot>/<Slug>'.
    Default: '<script dir>/../../workflow-launch2/plan_docs'. Point it elsewhere
    to launch a slug that is not in the launcher checkout. A missing slug
    directory throws before anything is created.

.PARAMETER Owner
    Repository owner. Default: intel-agency. Private repos are only supported
    under this owner — see the owner/visibility policy above.

.PARAMETER Visibility
    Repository visibility: public or private. Public works under any owner;
    private requires -Owner intel-agency.

.PARAMETER Count
    How many repos to create from the slug.

.PARAMETER Yes
    Non-interactive mode. Assume yes for all confirmations.

.PARAMETER LaunchEditor
    Launch the editor against the newly created repo after creation.

.PARAMETER TriggerHierarchyInit
    Whether to invoke `/gh-issue-tracking-init` on the new repo after cleanup.
    Default: $true.

.PARAMETER DryRun
    Forward -DryRun to all invoked scripts.

.PARAMETER Help
    Show this usage information and exit. Alias: -h.

.EXAMPLE
    ./scripts/create-repo-agent-context.ps1 `
        -Slug "gap-miner-v2" -Visibility public -Yes

.EXAMPLE
    ./scripts/create-repo-agent-context.ps1 `
        -Slug "my-app" -Count 2 -Yes -DryRun

.EXAMPLE
    ./scripts/create-repo-agent-context.ps1 `
        -Slug "my-app" -PlanDocsRoot '/path/to/other/plan_docs' -Yes

.NOTES
    Imported from the workflow-launch2 launcher; it predates the fold.
    See docs/plans/fold-workflow-launch2-into-service.md.
#>

[CmdletBinding()]
param(
    [Parameter(HelpMessage = 'Base app-plan slug (prefix).')]
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Slug,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$PlanDocsRoot = (Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs'),

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Owner = 'intel-agency',

    [Parameter()]
    [ValidateSet('public', 'private')]
    [string]$Visibility = 'public',

    [Parameter()]
    [ValidateScript({ $_ -ge 1 })]
    [int]$Count = 1,

    [Parameter()]
    [switch]$Yes,

    [Parameter()]
    [switch]$LaunchEditor,

    [Parameter()]
    [bool]$TriggerHierarchyInit = $true,

    [Parameter()]
    [switch]$DryRun,

    [Parameter()]
    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

function Show-Usage {
    Get-Help -Name $PSCommandPath -Detailed | Out-String | Write-Host
}

if ($Help) {
    Show-Usage
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Slug)) {
    Write-Host 'Error: -Slug is required.' -ForegroundColor Red
    Write-Host ''
    Show-Usage
    exit 1
}

Write-Host '=== create-repo-agent-context ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

$scriptDir = $PSScriptRoot
$createRepoScript = Join-Path $scriptDir 'create-repo-with-plan-docs.ps1'
$cleanupScript = Join-Path $scriptDir 'cleanup-template-state.ps1'
$permScript = Join-Path $scriptDir 'apply-headless-permissions.ps1'
$modelScript = Join-Path $scriptDir 'strip-model-settings.ps1'
$triggerScript = Join-Path $scriptDir 'trigger-gh-issue-tracking-init.ps1'
$importLabelsScript = Join-Path $scriptDir 'import-labels.ps1'
$repoFunctionsScript = Join-Path $scriptDir 'repo-functions.ps1'

foreach ($required in @($createRepoScript, $cleanupScript, $permScript, $modelScript, $triggerScript, $importLabelsScript, $repoFunctionsScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required script not found: $required"
    }
}

# Shared helpers (Test-OwnerVisibilityPolicy) — dot-sourced before the policy
# guard so nothing can reach `gh` or create a repo past it.
. $repoFunctionsScript

# Owner/visibility policy: intel-agency is an Enterprise-plan Organization, so
# only its private repos get Cloud Actions minutes; a free-tier User's private
# clone would have zero minutes and its dispatch workflows could never run.
if (-not (Test-OwnerVisibilityPolicy -Owner $Owner -Visibility $Visibility)) {
    throw ("Invalid owner/visibility combination: '{0}/{1}'. Private repos are only supported under the 'intel-agency' owner (Enterprise Cloud Actions minutes); free-tier private repos get no Actions minutes, so the clone's dispatch workflows could never run. Use -Owner intel-agency, or -Visibility public." -f $Owner, $Visibility)
}

# Agent-context template identity — hardcoded (this wrapper is agent-context-specific).
$TemplateRepoName = 'agent-context'
$TemplateOwner = 'intel-agency'

# Script-root-relative, so the pipeline runs from either repo root: plan docs
# come from the sibling workflow-launch2 slug store (-PlanDocsRoot overrides),
# clones land in the dynamic_workflows/ both repos have always launched into.
$PlanDocsDir = Join-Path $PlanDocsRoot $Slug
$CloneParentDir = Join-Path $PSScriptRoot '..' '..' 'dynamic_workflows'
if (-not (Test-Path -LiteralPath $PlanDocsDir)) {
    throw "Plan docs directory not found for slug '$Slug': $PlanDocsDir (resolved from -PlanDocsRoot '$PlanDocsRoot'; pass -PlanDocsRoot to point at a different plan_docs root)"
}

# Source labels file is this repo's own .github/.labels.json — the canonical
# dispatch label set. It must come from here, not the clone: the agent-context
# template ships no .labels.json, so label imports and bootstraps have no
# per-clone source. This is the file every label (including the dispatch label)
# is bootstrapped from.
$sourceLabelsFile = Join-Path $scriptDir '..' '.github/.labels.json'
if (-not (Test-Path -LiteralPath $sourceLabelsFile)) {
    throw "Source labels file not found: $sourceLabelsFile"
}

Write-Host "Calling create-repo-with-plan-docs.ps1..." -ForegroundColor Cyan

$createParams = @{
    RepoName          = $Slug
    Owner             = $Owner
    Visibility        = $Visibility
    Count             = $Count
    PlanDocsDir       = $PlanDocsDir
    CloneParentDir    = $CloneParentDir
    TemplateRepoName  = $TemplateRepoName
    TemplateOwner     = $TemplateOwner
}
if ($Yes)        { $createParams['Yes'] = $true }
if ($LaunchEditor){ $createParams['LaunchEditor'] = $true }
if ($DryRun)     { $createParams['DryRun'] = $true }

# Invoke the existing workflow. It returns each clone path on the pipeline
# (Write-Output) and signals failure via its exit code (exit 1 on error, exit 0
# on success — the script owns both, so $LASTEXITCODE is authoritative here).
# A -DryRun launch never creates the clone directory (the pipeline makes no
# filesystem changes), so the container check applies to real runs only.
$clonePaths = @(& $createRepoScript @createParams | Where-Object {
    $_ -and ($DryRun -or (Test-Path -LiteralPath $_ -PathType Container))
})
if ($LASTEXITCODE -ne 0) {
    throw "create-repo-with-plan-docs failed (exit code $LASTEXITCODE)."
}
if ($clonePaths.Count -eq 0) {
    throw 'create-repo-with-plan-docs returned no clone paths.'
}

Write-Host ''
Write-Host "Found $($clonePaths.Count) freshly cloned repo(s):" -ForegroundColor Cyan
foreach ($p in $clonePaths) { Write-Host "  - $p" -ForegroundColor DarkGray }
Write-Host ''

foreach ($clonePath in $clonePaths) {
    $repoName = Split-Path -Leaf $clonePath
    $repoFullName = "$Owner/$repoName"

    Write-Host "=== post-clone: $repoFullName ===" -ForegroundColor Cyan

    # Step 2: Class-2 cleanup
    Write-Host 'Running cleanup-template-state.ps1...' -ForegroundColor Cyan -NoNewline
    $cleanupParams = @{ RepoRoot = $clonePath }
    if ($DryRun) { $cleanupParams['DryRun'] = $true }
    & $cleanupScript @cleanupParams
    Write-Host ' done' -ForegroundColor Green

    # Step 3: Apply headless-safe permissions (ask -> allow, deny preserved).
    # MUST run before the seed-commit amend so the relaxed permissions ship in
    # the pushed commit. See apply-headless-permissions.ps1 for the root cause.
    Write-Host 'Applying headless permissions...' -ForegroundColor Cyan -NoNewline
    $permParams = @{ RepoRoot = $clonePath }
    if ($DryRun) { $permParams['DryRun'] = $true }
    & $permScript @permParams
    Write-Host ' done' -ForegroundColor Green

    # Step 3.5: Strip all model pins (agent frontmatter `model:` + project
    # config `model`/`small_model`). MUST run before the seed-commit amend so
    # the stripped config ships in the pushed commit. With the pins gone every
    # layer falls back to the orchestrator-service dispatch `--model
    # qwencloud/qwen3.7-max` / runtime image config instead of the template's
    # per-tier overrides (glm-5.3 / glm-5.3-flash). The template itself keeps its
    # models for non-orchestrator interactive clones. See
    # strip-model-settings.ps1 for the root cause.
    Write-Host 'Stripping model pins...' -ForegroundColor Cyan -NoNewline
    $modelParams = @{ RepoRoot = $clonePath }
    if ($DryRun) { $modelParams['DryRun'] = $true }
    & $modelScript @modelParams
    Write-Host ' done' -ForegroundColor Green

    # Amend the seed commit to include the cleanup + permission + model changes,
    # then force-push it back over main: stage 1 already pushed the pre-cleanup
    # seed commit, so an amend that stays local would leave origin/main shipping
    # the template's ask-permissions and model pins — exactly what steps 3/3.5
    # exist to strip. --force-with-lease is safe because the clone is ours alone
    # since that push; stage 1's own post-rebase amend uses the same pattern.
    if (-not $DryRun) {
        Write-Host 'Amending seed commit with cleanup + permissions + stripped models...' -ForegroundColor Cyan -NoNewline
        Push-Location -LiteralPath $clonePath
        try {
            & git add .
            & git commit --amend --no-edit --message "Seed $repoName from template with plan docs, placeholder replacements, Class-2 cleanup, headless permissions, and stripped model pins"
            if ($LASTEXITCODE -ne 0) {
                throw "git commit --amend failed (exit code $LASTEXITCODE) in $clonePath."
            }
            & git push --force-with-lease origin HEAD:main
            if ($LASTEXITCODE -ne 0) {
                throw "git push --force-with-lease failed (exit code $LASTEXITCODE) in $clonePath — the amended seed commit did not reach origin/main."
            }
        }
        finally {
            Pop-Location
        }
        Write-Host ' done' -ForegroundColor Green
    }

    # Step 4: Import this repo's full label set into the new repo so the
    # dispatch label (and every other tracking label) exists before the trigger.
    # import-labels.ps1 only creates/updates missing labels, so it is idempotent
    # and safe to re-run.
    Write-Host "Importing labels into $repoFullName..." -ForegroundColor Cyan
    $importParams = @{
        Repo       = $repoFullName
        LabelsFile = $sourceLabelsFile
    }
    if ($DryRun) { $importParams['DryRun'] = $true }
    & $importLabelsScript @importParams
    if ($LASTEXITCODE -ne 0) {
        throw "import-labels.ps1 failed (exit code $LASTEXITCODE) on $repoFullName."
    }
    Write-Host ' done' -ForegroundColor Green

    # Step 5: Dispatch /gh-issue-tracking-init
    # Labeled gh-issue-tracking:direct-body so the orchestrator webhook runs the
    # issue body verbatim as a prompt, invoking the skill. The label is already
    # imported above; BootstrapLabelsFile points at this repo's source file as
    # a safety net for Ensure-DispatchBootstrapLabel (the clone may lack
    # .labels.json).
    if ($TriggerHierarchyInit) {
        Write-Host "Running trigger-gh-issue-tracking-init.ps1 on $repoFullName..." -ForegroundColor Cyan
        $triggerParams = @{
            Repo                = $repoFullName
            Labels              = @('gh-issue-tracking:direct-body')
            BootstrapLabelsFile = $sourceLabelsFile
        }
        if ($DryRun) { $triggerParams['DryRun'] = $true }
        & $triggerScript @triggerParams
        Write-Host ' done' -ForegroundColor Green
    }
    else {
        Write-Verbose "-TriggerHierarchyInit is $false; skipping trigger on $repoFullName"
    }
}

Write-Host '=== all done ===' -ForegroundColor Green
