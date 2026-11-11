#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Normalize model settings in a freshly cloned orchestrator-dispatched instance:
    strip the per-tier pins, stamp the dispatch pin.

.DESCRIPTION
    opencode resolves the effective model in precedence order: built-in <
    global config < project config < session < AGENT FRONTMATTER model:. The
    swarm-context template ships a per-tier model mix at multiple layers — agent
    frontmatter plus the root `opencode.json` it stamps since the v2 migration
    (opencode v2 no longer reads `.opencode/opencode.jsonc`). Those pins are
    correct for INTERACTIVE use — the template must KEEP them, because it also
    seeds repos that are NOT driven by the dispatch pipeline and would otherwise
    be left with no model settings at all. But on headless dispatches the
    receiver owns model selection: the stamped root `opencode.json` `model` pin
    (O1, `zai-coding-plan/glm-5.3` — docs/plans/charlie68-incident-followups.md)
    is the dispatch default, and any agent frontmatter pin would override it.

    This script therefore does two things to the cloned instance:

      1. STRIP the overriding pins: agent frontmatter (.opencode/agents/*.md)
         top-level `model:` lines are deleted (the agent then inherits the
         project-config model), and legacy project config
         (.opencode/opencode.jsonc/.json — the v1 config location) top-level
         `model`/`small_model` keys are deleted (JSONC comma hygiene included).

      2. STAMP the dispatch pin: the root `opencode.json` (v2's config
         location, stamped by the template) top-level `"model"` key is set to
         -PinModel. A missing root file is left missing (pre-migration clones
         are an S3 fleet decision, not this script's job) and reported.

    SCOPE: Only invoked from create-repo-agent-context.ps1 — the orchestrator-
    dispatch seeding path. Repos cloned for NON-orchestrator (interactive) use
    never run this script, so the template's per-tier models stay intact for
    them. The template itself keeps its model pins.

    Idempotent: already-absent pins are left untouched; an already-correct root
    pin is left byte-identical. Safe to re-run.

.PARAMETER RepoRoot
    Absolute or relative path to the freshly cloned repository root.

.PARAMETER PinModel
    The dispatch model pin stamped into the root opencode.json `model` key.
    Default `zai-coding-plan/glm-5.3` (owner decision O1, 2026-10-24).

.PARAMETER DryRun
    Log planned operations without touching the filesystem.

.EXAMPLE
    ./scripts/strip-model-settings.ps1 -RepoRoot "/tmp/clones/my-app-delta12"

.EXAMPLE
    ./scripts/strip-model-settings.ps1 -RepoRoot ".\my-app-delta12" -DryRun

.NOTES
    Runs AFTER clone + placeholder replacement + Class-2 cleanup + headless
    permissions but BEFORE the seed-commit amend, so the normalized models ship
    in the pushed seed commit. Sibling override to apply-headless-permissions.ps1.
    Root cause: opencode precedence makes agent frontmatter `model:` the decisive
    layer, so every frontmatter pin defeats the stamped root-config model.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, HelpMessage = 'Path to the freshly cloned repository root.')]
    [ValidateNotNullOrEmpty()]
    [string]$RepoRoot,

    [Parameter(HelpMessage = 'Dispatch model pin stamped into the root opencode.json (O1 default).')]
    [ValidateNotNullOrEmpty()]
    [string]$PinModel = 'zai-coding-plan/glm-5.3',

    [Parameter(HelpMessage = 'Log planned operations without touching the filesystem.')]
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# UTF-8 without BOM — these are committed repo files; never introduce a BOM.
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

Write-Host '=== strip-model-settings ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    if ($DryRun) {
        # A -DryRun launch never creates the clone directory, so there is no
        # tree to walk — mirror the no-op instead of failing the pipeline.
        Write-Host '[dry-run] RepoRoot does not exist yet (clone is simulated) — nothing to strip.' -ForegroundColor Yellow
        exit 0
    }
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
            elseif ($trimmed -match '^(.*),(\s*//[^"]*)$') {
                # Dangling comma ahead of a trailing line comment:
                # `"key": v, // note` — drop just the comma. The comment
                # tail must be quote-free so a `//` inside a string value
                # is never mistaken for a comment.
                $out[$lastKeptIdx] = "$($Matches[1])$($Matches[2])"
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

# ── 3. Root opencode.json: stamp the dispatch model pin (O1) ─────────────────
# v2's config location, stamped by the template (root opencode.json replaces
# the dead .opencode/opencode.jsonc). The template's own pin value stays right
# for interactive clones; dispatched clones get the O1 pin here. Only the
# top-level "model" key is touched — small_model and everything else ride the
# template byte-for-byte. Line-based like step 2 so the file is preserved
# except the one key (a full JSON round-trip would reformat the doc).

$rootConfigPath = Join-Path $resolvedRoot 'opencode.json'

if (Test-Path -LiteralPath $rootConfigPath) {
    $raw = [System.IO.File]::ReadAllText($rootConfigPath, $utf8NoBom)
    $le = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
    $lines = $raw -split "\r?\n"

    # Top-level classification (same brace-depth walk as step 2; the root doc
    # is strict JSON but the classifier is comment-safe anyway).
    $depth = 0
    $modelLineIdx = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $isKey = ($depth -eq 1) -and ($lines[$i] -match '^\s*"model"\s*:')
        if ($isKey -and $modelLineIdx -lt 0) { $modelLineIdx = $i }
        $depth += Get-BraceDelta -Line $lines[$i]
    }

    if ($modelLineIdx -ge 0) {
        $already = $lines[$modelLineIdx] -match [regex]::Escape('"' + $PinModel + '"')
        if ($already) {
            Write-Host " opencode.json: model pin already $PinModel (unchanged)" -ForegroundColor DarkGray
        }
        else {
            $newLine = $lines[$modelLineIdx] -replace '("[^"]*"\s*:\s*")[^"]*(")', ('$1' + $PinModel + '$2')
            $lines[$modelLineIdx] = $newLine
            if ($DryRun) {
                Write-Host (" [dry-run] opencode.json: would stamp model = {0}" -f $PinModel) -ForegroundColor Yellow
            }
            else {
                [System.IO.File]::WriteAllText($rootConfigPath, ($lines -join $le), $utf8NoBom)
                Write-Host (" opencode.json: stamped model = {0}" -f $PinModel) -ForegroundColor DarkGray
            }
        }
    }
    else {
        # No top-level model key: insert one directly after the opening brace
        # line. Comma hygiene: append a comma unless the object is empty
        # (next non-blank line closes it).
        $insertIdx = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '\{') { $insertIdx = $i + 1; break }
        }
        if ($insertIdx -gt 0 -and $insertIdx -lt $lines.Count) {
            $needsComma = $true
            for ($j = $insertIdx; $j -lt $lines.Count; $j++) {
                if ($lines[$j].Trim() -eq '') { continue }
                if ($lines[$j] -match '^\s*[}]') { $needsComma = $false }
                break
            }
            $modelLine = '  "model": "' + $PinModel + '"' + $(if ($needsComma) { ',' } else { '' })
            if ($DryRun) {
                Write-Host (" [dry-run] opencode.json: would insert model = {0}" -f $PinModel) -ForegroundColor Yellow
            }
            else {
                $out = [System.Collections.Generic.List[string]]::new()
                $out.AddRange([string[]]$lines)
                $out.Insert($insertIdx, $modelLine)
                [System.IO.File]::WriteAllText($rootConfigPath, ($out -join $le), $utf8NoBom)
                Write-Host (" opencode.json: inserted model = {0}" -f $PinModel) -ForegroundColor DarkGray
            }
        }
        else {
            Write-Host ' opencode.json: no top-level object found — pin not stamped' -ForegroundColor Yellow
        }
    }
}
else {
    Write-Host ' opencode.json (root) not found — pin not stamped (pre-v2-template clone; see migration S3)' -ForegroundColor Yellow
}

Write-Host '=== strip-model-settings complete ===' -ForegroundColor Green
