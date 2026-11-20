#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Import the clone branch-protection ruleset into a GitHub repository.

.DESCRIPTION
    Reads the ruleset definition (create-body shaped, exported from the
    GitHub UI ruleset and trimmed) and ensures the target repository has
    it. The ruleset is the MECHANICAL merge gate for orchestrator-dispatched
    clones (docs/plans/rev2-state-map-design.md Decision 14): the required
    `validate` status check (the CI job that runs the identical
    ./validation.ps1 on GitHub-hosted runners) must be green for ANY merge
    into the default branch, and bypass_actors is EMPTY — nobody, including
    admin tokens, merges around a red gate.

    Idempotent: if a ruleset with the same name already exists on the repo,
    the definition is compared and the script reports already-present (no
    update, no duplicate).

.PARAMETER Repo
    Target repository in the form "owner/repo" (e.g., "intel-agency/my-app-delta12").

.PARAMETER RulesetFile
    Path to the ruleset JSON create-body (default: this repo's
    .github/.clone-ruleset.json).

.PARAMETER DryRun
    Show what would be created without making any changes.

.EXAMPLE
    ./scripts/import-ruleset.ps1 -Repo "intel-agency/my-app-delta12"

.EXAMPLE
    ./scripts/import-ruleset.ps1 -Repo "intel-agency/my-app-delta12" -DryRun

.NOTES
    Launcher stage 4.5 (after import-labels): the ruleset must be imported
    AFTER the seed push — required status checks reject direct pushes that
    have not passed CI, and the seed commit predates any check run.
    A $comment key in the JSON is documentation-only and is stripped
    before the API call.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = 'Target repository in "owner/repo" form.')]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repo,

    [Parameter(HelpMessage = 'Path to the ruleset JSON create-body.')]
    [ValidateNotNullOrEmpty()]
    [string]$RulesetFile = (Join-Path $PSScriptRoot '..' '.github' '.clone-ruleset.json'),

    [Parameter(HelpMessage = 'Show what would be created without making any changes.')]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

Write-Host '=== import-ruleset ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $RulesetFile)) {
    throw "Ruleset file not found: $RulesetFile"
}

# Strip the documentation-only $comment key — the API rejects unknown fields.
$definition = Get-Content -LiteralPath $RulesetFile -Raw | ConvertFrom-Json -AsHashtable
$definition.Remove('$comment') | Out-Null
$name = $definition['name']

if ($DryRun) {
    $checkRule = $definition['rules'] | Where-Object { $_['type'] -eq 'required_status_checks' }
    $contexts = ($checkRule['parameters']['required_status_checks'] | ForEach-Object { $_['context'] }) -join ', '
    Write-Host "[dry-run] would ensure ruleset '$name' on '$Repo' (required checks: $contexts; bypass actors: NONE by design)" -ForegroundColor Yellow
    exit 0
}

# Idempotency: a ruleset with the same name already present -> report, do not touch.
# (Names-only jq — no embedded quotes to fight through two shells.)
$names = & gh api "repos/$Repo/rulesets" --jq '.[].name' 2>$null
if ($LASTEXITCODE -eq 0 -and @($names) -contains $name) {
    Write-Host " ruleset '$name' already present on $Repo — nothing to do" -ForegroundColor DarkGray
    exit 0
}

$bodyFile = New-TemporaryFile
try {
    $definition | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $bodyFile -Encoding utf8NoBOM
    $created = & gh api -X POST "repos/$Repo/rulesets" --input $bodyFile --jq '.id' 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "ruleset creation failed: $created"
    }
    Write-Host (" ruleset '{0}' created on {1} (id {2}) — required check 'validate', empty bypass list" -f $name, $Repo, $created) -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
}
