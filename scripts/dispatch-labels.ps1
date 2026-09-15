#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
Shared label-bootstrap helpers for dispatch-trigger scripts.

.DESCRIPTION
Functions only (no param() block, no top-level execution) so callers can
dot-source this library directly to reuse Ensure-DispatchBootstrapLabel without
running any dispatch logic. Extracted from trigger-project-setup.ps1 so both
trigger-project-setup.ps1 and trigger-gh-issue-tracking-init.ps1 share one
implementation. Do NOT add top-level statements here.
#>

function Get-BootstrapLabelDefinition {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LabelsFile,

        [Parameter(Mandatory = $true)]
        [string]$LabelName
    )

    if (-not (Test-Path -LiteralPath $LabelsFile)) {
        throw "Bootstrap labels file not found: $LabelsFile"
    }

    $labels = Get-Content -LiteralPath $LabelsFile -Raw | ConvertFrom-Json
    $label = $labels | Where-Object { $_.name -eq $LabelName } | Select-Object -First 1
    if (-not $label) {
        throw "Bootstrap label '$LabelName' not found in labels file '$LabelsFile'."
    }

    return $label
}

function Ensure-DispatchBootstrapLabel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetRepo,

        [Parameter(Mandatory = $true)]
        [string]$LabelsFile,

        [Parameter()]
        [string]$LabelName = 'orchestration:dispatch',

        [switch]$IsDryRun
    )

    $label = Get-BootstrapLabelDefinition -LabelsFile $LabelsFile -LabelName $LabelName
    $encodedLabelName = [uri]::EscapeDataString($LabelName)

    if ($IsDryRun) {
        Write-Host "[dry-run] Would ensure bootstrap label '$LabelName' exists on '$TargetRepo' using '$LabelsFile'." -ForegroundColor Yellow
        return
    }

    $checkResult = & gh api "repos/$TargetRepo/labels/$encodedLabelName" 2>&1
    if ($LASTEXITCODE -eq 0 -and $checkResult -notmatch '"message"') {
        Write-Verbose "Bootstrap label '$LabelName' already exists on '$TargetRepo'."
        return
    }

    $color = ([string]$label.color).Trim().TrimStart('#')
    $description = if ($null -ne $label.description) { [string]$label.description } else { '' }

    Write-Host ""
    Write-Host "Creating bootstrap label '$LabelName' on '$TargetRepo'..." -ForegroundColor Cyan -NoNewline
    $ghArgs = @(
        'api', "repos/$TargetRepo/labels", '-X', 'POST',
        '-f', "name=$LabelName",
        '-f', "color=$color"
    )
    if ($description -ne '') {
        $ghArgs += @('-f', "description=$description")
    }

    & gh @ghArgs *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create bootstrap label '$LabelName' on '$TargetRepo'."
    }

    Write-Host ' done' -ForegroundColor Green
}
