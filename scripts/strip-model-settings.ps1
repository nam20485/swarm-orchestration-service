#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Strip model settings from a freshly cloned orchestrator-dispatched instance.

.DESCRIPTION
    opencode resolves the effective model in precedence order: built-in <
    global config < project config (.opencode/opencode.jsonc) < session (--model)
    < AGENT FRONTMATTER model:. The agent-context template ships a per-tier model
    mix at BOTH layers — agent frontmatter (glm-5.3-flash for
    implementers/specialists; glm-5.3 for coordinators) AND a project-config
    `model: glm-5.3` / `small_model: glm-4.5-air`. Those are correct for
    INTERACTIVE use — the template must KEEP them, because it also seeds repos
    that are NOT driven by orchestrator-service and would otherwise be left with
    no model settings at all. But on orchestrator-service headless dispatches
    they OVERRIDE the dispatch defaults (`--model qwencloud/qwen3.7-max
    --variant high`): subagents run glm-5.3-flash and the orchestrator runs
    glm-5.3, defeating the model selection the orchestrator-service runtime
    image owns.

    This script REMOVES (not rewrites) the model pins from the cloned instance
    so every layer falls back to the orchestrator-service dispatch/runtime
    settings:

      1. Agent frontmatter (.opencode/agents/*.md): delete every top-level
         `model:` line inside the frontmatter fence. With no frontmatter pin
         the agent inherits the session model (the dispatch `--model`).

      2. Project config (.opencode/opencode.jsonc/.json): delete the top-level
         `"model"` and `"small_model"` keys (JSONC comma hygiene included) so
         the project layer no longer overrides the global/dispatch defaults.

    SCOPE: Only invoked from create-repo-agent-context.ps1 — the orchestrator-
    dispatch seeding path. Repos cloned for NON-orchestrator (interactive) use
    never run this script, so the template's per-tier models stay intact for
    them. The template itself keeps its model pins.

    Idempotent: already-absent pins are left untouched. Safe to re-run.

.PARAMETER RepoRoot
    Absolute or relative path to the freshly cloned repository root.

.PARAMETER DryRun
    Log planned operations without touching the filesystem.

.EXAMPLE
    ./scripts/strip-model-settings.ps1 -RepoRoot "/tmp/clones/my-app-delta12"

.EXAMPLE
    ./scripts/strip-model-settings.ps1 -RepoRoot ".\my-app-delta12" -DryRun

.NOTES
    Runs AFTER clone + placeholder replacement + Class-2 cleanup + headless
    permissions but BEFORE the seed-commit amend, so the stripped models ship
    in the pushed seed commit. Sibling override to apply-headless-permissions.ps1.
    Root cause: opencode precedence makes agent frontmatter `model:` the decisive
    layer, so the dispatch `--model` and global `model` are both defeated by the
    workspace agent definitions cloned from the template.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = 'Path to the freshly cloned repository root.')]
    [ValidateNotNullOrEmpty()]
    [string]$RepoRoot,

    [Parameter(HelpMessage = 'Log planned operations without touching the filesystem.')]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# UTF-8 without BOM — these are committed repo files; never introduce a BOM.
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

Write-Host '=== strip-model-settings ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "RepoRoot not found: $RepoRoot"
}

$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Write-Host "RepoRoot: $resolvedRoot" -ForegroundColor DarkGray

# ── 1. Agent frontmatter: remove top-level `model:` lines ────────────────────

$agentsDir = Join-Path $resolvedRoot '.opencode/agents'
$totalStripped = 0
$agentsTouched = 0

if (Test-Path -LiteralPath $agentsDir) {
    $agentFiles = @(Get-ChildItem -LiteralPath $agentsDir -File -Filter '*.md' -Force)
    foreach ($file in $agentFiles) {
        $path = $file.FullName
        $raw = [System.IO.File]::ReadAllText($path, $utf8NoBom)

        # Preserve the file's line ending (CRLF or LF) and trailing newline.
        $le = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
        $lines = $raw -split "\r?\n"

        $inFrontmatter = $false
        $fenceCount = 0
        $strippedThisFile = 0
        $out = [System.Collections.Generic.List[string]]::new()

        foreach ($line in $lines) {
            if ($line -match '^---\s*$') {
                $fenceCount++
                if ($fenceCount -eq 1) {
                    $inFrontmatter = $true
                }
                elseif ($fenceCount -ge 2) {
                    $inFrontmatter = $false
                }
                $out.Add($line)
                continue
            }

            # A column-0 `model:` key (top-level frontmatter field). DROP the
            # line entirely so the agent inherits the session/dispatch model.
            if ($inFrontmatter -and $line -match '^model:\s*\S') {
                $strippedThisFile++
                continue
            }

            $out.Add($line)
        }

        if ($strippedThisFile -gt 0) {
            $result = ($out -join $le)
            if ($DryRun) {
                Write-Host (" [dry-run] {0}: would remove {1} model pin(s)" -f $file.Name, $strippedThisFile) -ForegroundColor Yellow
            }
            else {
                [System.IO.File]::WriteAllText($path, $result, $utf8NoBom)
                Write-Host (" {0}: removed {1} model pin(s)" -f $file.Name, $strippedThisFile) -ForegroundColor DarkGray
            }
            $totalStripped += $strippedThisFile
            $agentsTouched++
        }
        else {
            Write-Host " $($file.Name): no model pin (unchanged)" -ForegroundColor DarkGray
        }
    }
}
else {
    Write-Host ' .opencode/agents/ not found — skipping agent frontmatter' -ForegroundColor DarkGray
}

Write-Host ("Agent frontmatter: {0} pin(s) removed across {1} file(s)" -f $totalStripped, $agentsTouched) -ForegroundColor Green

# ── 2. Project config opencode.jsonc/.json: remove top-level model keys ──────

# Brace depth delta of a JSONC line, ignoring string literals (e.g. "{env:X}")
# and trailing // comments, so nested keys are never mistaken for top-level.
function Get-BraceDelta {
    param([string]$Line)

    $delta = 0
    $inString = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $ch = $Line[$i]
        if ($inString) {
            if ($ch -eq '\') { $i++ }
            elseif ($ch -eq '"') { $inString = $false }
            continue
        }
        if ($ch -eq '"') { $inString = $true; continue }
        if ($ch -eq '/' -and ($i + 1) -lt $Line.Length -and $Line[$i + 1] -eq '/') { break }
        if ($ch -eq '{') { $delta++ }
        elseif ($ch -eq '}') { $delta-- }
    }
    return $delta
}

$jsoncPath = Join-Path $resolvedRoot '.opencode/opencode.jsonc'
$jsonPath = Join-Path $resolvedRoot '.opencode/opencode.json'
$configFound = $false
$configTouched = $false

foreach ($cfgPath in @($jsoncPath, $jsonPath)) {
    if (-not (Test-Path -LiteralPath $cfgPath)) { continue }
    $configFound = $true

    $raw = [System.IO.File]::ReadAllText($cfgPath, $utf8NoBom)
    $le = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
    $lines = $raw -split "\r?\n"

    # Pass 1: classify each line (depth at line start; is it a top-level
    # "model" / "small_model" key line?).
    $depth = 0
    $isKeyLine = [System.Collections.Generic.List[bool]]::new()
    foreach ($line in $lines) {
        $isKey = ($depth -eq 1) -and ($line -match '^\s*"model"\s*:' -or $line -match '^\s*"small_model"\s*:')
        $isKeyLine.Add($isKey)
        $depth += Get-BraceDelta -Line $line
    }

    if (-not ($isKeyLine -contains $true)) {
        Write-Host " $(Split-Path -Leaf $cfgPath): no top-level model/small_model keys (unchanged)" -ForegroundColor DarkGray
        break # only one of .jsonc / .json exists
    }

    # Pass 2: build output; when a closer (} or ]) directly follows a removed
    # key run, trim the dangling comma on the preceding kept line.
    $out = [System.Collections.Generic.List[string]]::new()
    $lastKeptIdx = -1
    $afterRemovedRun = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($isKeyLine[$i]) { $afterRemovedRun = $true; continue }

        if ($line -match '^\s*[}\]]' -and $afterRemovedRun -and $lastKeptIdx -ge 0) {
            $prev = $out[$lastKeptIdx]
            $trimmed = $prev.TrimEnd()
            if ($trimmed.EndsWith(',')) {
                $out[$lastKeptIdx] = $trimmed.Substring(0, $trimmed.Length - 1)
            }
        }

        $out.Add($line)
        if ($line.Trim() -ne '') {
            $lastKeptIdx = $out.Count - 1
            $afterRemovedRun = $false
        }
    }

    if ($DryRun) {
        Write-Host (" [dry-run] {0}: would remove top-level model/small_model key(s)" -f (Split-Path -Leaf $cfgPath)) -ForegroundColor Yellow
    }
    else {
        [System.IO.File]::WriteAllText($cfgPath, ($out -join $le), $utf8NoBom)
        Write-Host (" {0}: removed top-level model/small_model key(s)" -f (Split-Path -Leaf $cfgPath)) -ForegroundColor DarkGray
    }
    $configTouched = $true
    break # only one of .jsonc / .json exists
}

if (-not $configFound) {
    Write-Host ' .opencode/opencode.json(c) not found — skipping project config' -ForegroundColor DarkGray
}

Write-Host '=== strip-model-settings complete ===' -ForegroundColor Green
