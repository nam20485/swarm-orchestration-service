#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Trigger `/gh-issue-tracking-init` on a freshly seeded agent-context clone.

.DESCRIPTION
    Creates a dispatch issue on the target repo whose body is the single-line
    trigger `/gh-issue-tracking-init`. By default the issue is labeled
    `gh-issue-tracking:direct-body` so the orchestrator webhook runs the body
    verbatim as a prompt (the `direct-body` match clause), invoking the skill.

    Each label in -Labels is bootstrapped from -BootstrapLabelsFile (created on
    the target repo if missing) before being attached to the dispatch issue.
    To create a bare, unlabeled issue, pass -Labels @().

    To use the legacy orchestration method instead, pass
    -Labels 'orchestration:dispatch'.

    This is the replacement trigger for `trigger-project-setup.ps1`: the legacy
    script dispatches `/orchestrate-dynamic-workflow $workflow_name = project-setup`
    via `create-dispatch-issue.ps1`, which is incompatible with agent-context's
    new structure. This script dispatches the correct follow-up.

    Reuses the existing `create-dispatch-issue.ps1` for issue creation and
    dot-sources the shared `dispatch-labels.ps1` library for the
    `Ensure-DispatchBootstrapLabel` helper.

.PARAMETER Repo
    Target repository in "owner/repo" form (required).

.PARAMETER BootstrapLabelsFile
    Path to the clone's `.github/.labels.json` used to bootstrap (create on the
    target repo) any labels in -Labels that do not yet exist. Throws if missing
    when -Labels is non-empty and -DryRun is not.

.PARAMETER Labels
    Labels to attach to the dispatch issue. Each is bootstrapped from
    -BootstrapLabelsFile if provided. Default: @('gh-issue-tracking:direct-body'),
    which the orchestrator's direct-body clause matches to run the issue body
    verbatim. Pass 'orchestration:dispatch' for the legacy method, or @() for a
    bare, unlabeled issue.

.PARAMETER DryRun
    Show what would be created without making any changes.

.EXAMPLE
    # Default: dispatch issue labeled gh-issue-tracking:direct-body (orchestrator runs the body).
    ./scripts/trigger-gh-issue-tracking-init.ps1 `
        -Repo "intel-agency/my-app-delta12" `
        -BootstrapLabelsFile "./clones/my-app-delta12/.github/.labels.json"

.EXAMPLE
    # Legacy method: dispatch issue labeled orchestration:dispatch.
    ./scripts/trigger-gh-issue-tracking-init.ps1 `
        -Repo "intel-agency/my-app-delta12" `
        -BootstrapLabelsFile "./clones/my-app-delta12/.github/.labels.json" `
        -Labels 'orchestration:dispatch'

.EXAMPLE
    ./scripts/trigger-gh-issue-tracking-init.ps1 `
        -Repo "intel-agency/my-app-delta12" -DryRun

.NOTES
    Part of W1.5 (replace broken hierarchy-init trigger) from the
    template-content-strategy plan. Coexists with legacy
    `trigger-project-setup.ps1` — does not replace or modify it.
    See docs/plans/workflow-launch2-clone-pipeline-class2-cleanup.md.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = 'Target repository in "owner/repo" form.')]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repo,

    [Parameter(HelpMessage = 'Path to the clone''s .github/.labels.json used to bootstrap labels in -Labels that do not yet exist on the target repo.')]
    [string]$BootstrapLabelsFile,

    [Parameter(HelpMessage = 'Labels to attach to the dispatch issue (each bootstrapped from -BootstrapLabelsFile if provided). Default: gh-issue-tracking:direct-body. Pass orchestration:dispatch for the legacy method, or @() for a bare issue.')]
    [string[]]$Labels = @('gh-issue-tracking:direct-body'),

    [Parameter(HelpMessage = 'Show what would be created without making any changes.')]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

Write-Host '=== trigger-gh-issue-tracking-init ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

$scriptDir = $PSScriptRoot
$createDispatch = Join-Path $scriptDir 'create-dispatch-issue.ps1'
if (-not (Test-Path -LiteralPath $createDispatch)) {
    throw "Required script not found: $createDispatch"
}

# Dot-source the shared dispatch-labels library for Ensure-DispatchBootstrapLabel.
# (Functions only; does not run any dispatch logic, unlike trigger-project-setup.ps1.)
$dispatchLabels = Join-Path $scriptDir 'dispatch-labels.ps1'
if (-not (Test-Path -LiteralPath $dispatchLabels)) {
    throw "Required helper not found: $dispatchLabels (for Ensure-DispatchBootstrapLabel)"
}
. $dispatchLabels

# Bootstrap the dispatch labels from the labels file (create on the target repo
# if missing) so they can be attached to the issue. Skipped when -Labels is empty.
if ($Labels -and $Labels.Count -gt 0) {
    if ($BootstrapLabelsFile) {
        if (-not (Test-Path -LiteralPath $BootstrapLabelsFile)) {
            throw "Bootstrap labels file not found: $BootstrapLabelsFile"
        }
        foreach ($labelName in $Labels) {
            Write-Host "Bootstrapping label '$labelName' on $Repo..." -ForegroundColor Cyan -NoNewline
            Ensure-DispatchBootstrapLabel -TargetRepo $Repo -LabelsFile $BootstrapLabelsFile -LabelName $labelName -IsDryRun:$DryRun
            Write-Host ' done' -ForegroundColor Green
        }
    }
    else {
        Write-Verbose 'No BootstrapLabelsFile provided; skipping label bootstrap (labels must already exist on the target repo).'
    }
}
else {
    Write-Verbose 'No labels requested; dispatch issue will be created unlabeled.'
}

# Build the dispatch issue body: a single-line invocation of the skill.
# No args — the skill's defaults (current repo + plan_docs/) are exactly the
# right state for a freshly seeded clone.
$body = '/gh-issue-tracking-init'
$title = 'gh-issue-tracking-init'

Write-Host "Creating dispatch issue on $Repo..." -ForegroundColor Cyan -NoNewline
if ($DryRun) {
    Write-Host " [dry-run] would create issue '$title' with body: '$body'" -ForegroundColor Yellow
}

$dispatchParams = @{
    Repo  = $Repo
    Title = $title
    Body  = $body
}
if ($Labels -and $Labels.Count -gt 0) {
    $dispatchParams['Labels'] = @($Labels)
}
if ($DryRun) { $dispatchParams['DryRun'] = $true }

& $createDispatch @dispatchParams

Write-Host '=== trigger complete ===' -ForegroundColor Green
