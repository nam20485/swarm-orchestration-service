#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Create a new `agent-context`-seeded repo with Class-2 cleanup and
    `/gh-issue-tracking-init` hierarchy dispatch.

.DESCRIPTION
    Thin wrapper over the existing `create-repo-with-plan-docs.ps1` + the new
    `cleanup-template-state.ps1` and `trigger-gh-issue-tracking-init.ps1`.

    It accepts the same core parameters as `create-repo-from-slug.ps1` (Slug,
    Owner, Visibility, Count, Yes) plus agent-context-specific ones
    (-TriggerHierarchyInit, default $true). The legacy project-setup dispatch
    (`/orchestrate-dynamic-workflow $workflow_name = project-setup`) is never
    fired by this wrapper, so other templates relying on the legacy trigger are
    unaffected.

    Pipeline order per repo:
      1. create-repo-with-plan-docs.ps1 -SkipProjectSetup <params>
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
          -LabelsFile <launcher>/.github/.labels.json
      5. trigger-gh-issue-tracking-init.ps1 -Repo "$Owner/$RepoName"
          -BootstrapLabelsFile <launcher>/.github/.labels.json

    The existing `create-repo-with-plan-docs.ps1` main loop is unchanged; only
    the optional `-SkipProjectSetup` switch is added (default behavior
    identical).

.PARAMETER Slug
    Base app-plan slug (prefix). A random suffix is appended to form the final
    repo name.

.PARAMETER Owner
    Repository owner. Default: intel-agency.

.PARAMETER Visibility
    Repository visibility: public or private.

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

.NOTES
    Part of W1.5 (replace broken hierarchy-init trigger) from the
    template-content-strategy plan.
    See docs/plans/workflow-launch2-clone-pipeline-class2-cleanup.md.
#>

[CmdletBinding()]
param(
    [Parameter(HelpMessage = 'Base app-plan slug (prefix).')]
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Slug,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Owner = 'nam20485',

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

foreach ($required in @($createRepoScript, $cleanupScript, $permScript, $modelScript, $triggerScript, $importLabelsScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required script not found: $required"
    }
}

# Agent-context template identity — hardcoded (this wrapper is agent-context-specific).
$TemplateRepoName = 'agent-context'
$TemplateOwner = 'intel-agency'

# Launcher conventions.
$PlanDocsDir = "./plan_docs/$Slug"
$CloneParentDir = '../dynamic_workflows'

# Source labels file lives in the launcher repo's .github/ (not necessarily the
# clone's), so label imports work even when the agent-context template lacks a
# .labels.json. This is the file every label (including the dispatch label) is
# bootstrapped from.
$sourceLabelsFile = Join-Path $scriptDir '..' '.github/.labels.json'
if (-not (Test-Path -LiteralPath $sourceLabelsFile)) {
    throw "Source labels file not found: $sourceLabelsFile"
}

Write-Host "Calling create-repo-with-plan-docs.ps1 (with -SkipProjectSetup)..." -ForegroundColor Cyan

$createParams = @{
    RepoName          = $Slug
    Owner             = $Owner
    Visibility        = $Visibility
    Count             = $Count
    PlanDocsDir       = $PlanDocsDir
    CloneParentDir    = $CloneParentDir
    TemplateRepoName  = $TemplateRepoName
    TemplateOwner     = $TemplateOwner
    SkipProjectSetup  = $true
}
if ($Yes)        { $createParams['Yes'] = $true }
if ($LaunchEditor){ $createParams['LaunchEditor'] = $true }
if ($DryRun)     { $createParams['DryRun'] = $true }

# Invoke the existing workflow. It returns each clone path on the pipeline
# (Write-Output) and signals failure via its exit code (exit 1).
$clonePaths = @(& $createRepoScript @createParams | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) })
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

    # Amend the seed commit to include the cleanup + permission + model changes.
    if (-not $DryRun) {
        Write-Host 'Amending seed commit with cleanup + permissions + stripped models...' -ForegroundColor Cyan -NoNewline
        Push-Location -LiteralPath $clonePath
        try {
            & git add .
            & git commit --amend --no-edit --message "Seed $repoName from template with plan docs, placeholder replacements, Class-2 cleanup, headless permissions, and stripped model pins"
        }
        finally {
            Pop-Location
        }
        Write-Host ' done' -ForegroundColor Green
    }

    # Step 4: Import the launcher's full label set into the new repo so the
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
    # imported above; BootstrapLabelsFile points at the launcher's source file as
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
