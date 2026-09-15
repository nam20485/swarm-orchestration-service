#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
    Relax agent-context permissions to headless-safe values on a freshly cloned
    orchestrator-dispatched instance.

.DESCRIPTION
    opencode resolves permissions in precedence order: built-in < global config
    < project config (.opencode/opencode.jsonc) < AGENT FRONTMATTER. The
    agent-context template ships restrictive `ask` entries (correct for
    INTERACTIVE use) at BOTH the project-config layer and — decisively — the
    agent-frontmatter layer. A headless orchestrator dispatch (`opencode run
    --attach`, no human responder) can NEVER answer an `ask`, so any `ask`
    resolves to a permanent deadlock (the run blocks until the watchdog kills
    only the client; the server-side session survives).

    This script rewrites the cloned instance's permission config so headless
    dispatches never block:

      1. Agent frontmatter (.opencode/agents/*.md): within the YAML `permission:`
         block, change every `ask` value to `allow`. EXPLICIT `deny` ENTRIES ARE
         PRESERVED — opencode evaluates all matching patterns and denies if ANY
         matches `deny`, so safety nets like `git push*: deny`, `sudo*: deny`,
         and `rm -rf /*: deny` remain in force. Only the unanswerable `ask`s
         (the deadlock source) become `allow`.

      2. Project config (.opencode/opencode.jsonc): replace the partial
         `permission` object with the `"allow"` shorthand so the project config
         no longer overrides the global allow with a partial object (this covers
         any tool not enumerated in an agent's frontmatter).

    SCOPE: Only invoked from create-repo-agent-context.ps1 — the orchestrator-
    dispatch seeding path. Repos cloned for NON-orchestrator (interactive) use
    never run this script, so the template's restrictive defaults stay intact
    for them. The template itself is intentionally left unchanged (it seeds
    every repo, orchestrator or otherwise).

    COORDINATOR EXEMPTION: coordinator agents (orchestrator, team-lead,
    team-orchestrator, planner) are SKIPPED entirely. Their deny-based
    permissions are a universal "must delegate, never implement" design rule
    managed in the template; relaxing them would grant a coordinator
    implementation capability. Only implementer/specialist agents are relaxed.

    Idempotent: an already-relaxed file is left untouched (no `ask` to match, no
    object to replace). Safe to re-run.

.PARAMETER RepoRoot
    Absolute or relative path to the freshly cloned repository root.

.PARAMETER DryRun
    Log planned operations without touching the filesystem.

.EXAMPLE
    ./scripts/apply-headless-permissions.ps1 -RepoRoot "/tmp/clones/my-app-delta12"

.EXAMPLE
    ./scripts/apply-headless-permissions.ps1 -RepoRoot ".\my-app-delta12" -DryRun

.NOTES
    Definitive fix for the recurring headless permission-ask deadlock. Runs
    AFTER clone + placeholder replacement + Class-2 cleanup but BEFORE the
    seed-commit amend, so the relaxed permissions ship in the pushed seed commit.
    See the root-cause analysis: opencode precedence built-in < global < project
    config < agent frontmatter; agent frontmatter is the decisive layer.
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

# Within an agent's `permission:` frontmatter block, a line whose YAML scalar
# value is `ask`. Captures the indent+key+colon (group 1) and any trailing
# whitespace/comment (group 2) so only the value token is swapped to `allow`.
# The key class [\w"*] matches simple keys (`edit`, `external_directory`) and
# the bash catch-all `"*"`, and deliberately does NOT match comment lines.
$askValueRe = [regex]'^(\s+[\w"*]+:\s*)ask(\s*(#.*)?)$'

# The partial permission object in opencode.jsonc (e.g. `{ "websearch": "allow" }`)
# that overrides the global `"allow"` shorthand at the project-config layer.
$permObjectRe = [regex]'"permission"\s*:\s*\{[^{}]*\}'

Write-Host '=== apply-headless-permissions ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "RepoRoot not found: $RepoRoot"
}

$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
Write-Host "RepoRoot: $resolvedRoot" -ForegroundColor DarkGray

# ── 1. Agent frontmatter: ask -> allow (preserve deny) ──────────────────────

$agentsDir = Join-Path $resolvedRoot '.opencode/agents'
$totalAsksRelaxed = 0
$agentsTouched = 0

# Coordinator agents are pure delegators: their restrictive deny-based
# permissions are a UNIVERSAL design rule (the orchestrator must never
# implement), managed in the template - NOT a headless-only concern. They must
# NOT be relaxed here: converting their bash catch-all `ask` to `allow` would
# grant a coordinator unrestricted implementation bash and break the
# must-delegate invariant. Their frontmatter carries no `ask` values anyway
# (they use `deny`), so skipping is correct and a no-op today; the guard makes
# the intent explicit and fails safe against future regressions.
$coordinatorAgents = @('orchestrator.md', 'team-lead.md', 'team-orchestrator.md', 'planner.md')

if (Test-Path -LiteralPath $agentsDir) {
    $agentFiles = @(Get-ChildItem -LiteralPath $agentsDir -File -Filter '*.md' -Force)
    foreach ($file in $agentFiles) {
        $path = $file.FullName

        if ($coordinatorAgents -contains $file.Name) {
            Write-Host " $($file.Name): coordinator (deny-managed in template) - skipped" -ForegroundColor DarkGray
            continue
        }

        $raw = [System.IO.File]::ReadAllText($path, $utf8NoBom)

        # Preserve the file's line ending (CRLF or LF) and trailing newline.
        $le = if ($raw.Contains("`r`n")) { "`r`n" } else { "`n" }
        $lines = $raw -split "\r?\n"

        $inFrontmatter = $false
        $inPermission = $false
        $fenceCount = 0
        $asksThisFile = 0
        $out = [System.Collections.Generic.List[string]]::new()

        foreach ($line in $lines) {
            if ($line -match '^---\s*$') {
                $fenceCount++
                if ($fenceCount -eq 1) {
                    $inFrontmatter = $true
                    $inPermission = $false
                }
                elseif ($fenceCount -ge 2) {
                    $inFrontmatter = $false
                    $inPermission = $false
                }
                $out.Add($line)
                continue
            }

            if ($inFrontmatter) {
                # A column-0 key (no leading whitespace) starts a new frontmatter
                # section. Set inPermission only for the `permission:` key.
                if ($line -match '^[A-Za-z_][A-Za-z0-9_]*:') {
                    $inPermission = $line -match '^permission:'
                }

                if ($inPermission) {
                    $m = $askValueRe.Match($line)
                    if ($m.Success) {
                        $line = $m.Groups[1].Value + 'allow' + $m.Groups[2].Value
                        $asksThisFile++
                    }
                }
            }

            $out.Add($line)
        }

        if ($asksThisFile -gt 0) {
            $result = ($out -join $le)
            if ($DryRun) {
                Write-Host (" [dry-run] {0}: would relax {1} ask(s) -> allow" -f $file.Name, $asksThisFile) -ForegroundColor Yellow
            }
            else {
                [System.IO.File]::WriteAllText($path, $result, $utf8NoBom)
                Write-Host (" {0}: relaxed {1} ask(s) -> allow" -f $file.Name, $asksThisFile) -ForegroundColor DarkGray
            }
            $totalAsksRelaxed += $asksThisFile
            $agentsTouched++
        }
        else {
            Write-Host " $($file.Name): no ask entries (unchanged)" -ForegroundColor DarkGray
        }
    }
}
else {
    Write-Host ' .opencode/agents/ not found — skipping agent frontmatter' -ForegroundColor DarkGray
}

Write-Host ("Agent frontmatter: {0} file(s), {1} ask(s) relaxed to allow (deny entries preserved)" -f $agentsTouched, $totalAsksRelaxed) -ForegroundColor Green

# ── 2. Project config opencode.jsonc: permission object -> "allow" ──────────

$jsoncPath = Join-Path $resolvedRoot '.opencode/opencode.jsonc'
$jsonPath = Join-Path $resolvedRoot '.opencode/opencode.json'
$configTouched = $false

foreach ($cfgPath in @($jsoncPath, $jsonPath)) {
    if (-not (Test-Path -LiteralPath $cfgPath)) { continue }

    $raw = [System.IO.File]::ReadAllText($cfgPath, $utf8NoBom)
    if ($permObjectRe.IsMatch($raw)) {
        $newRaw = $permObjectRe.Replace($raw, '"permission": "allow"', 1)
        if ($DryRun) {
            Write-Host (" [dry-run] {0}: would replace permission object with `"allow`" shorthand" -f (Split-Path -Leaf $cfgPath)) -ForegroundColor Yellow
        }
        else {
            [System.IO.File]::WriteAllText($cfgPath, $newRaw, $utf8NoBom)
            Write-Host (" {0}: permission object -> `"allow`" shorthand" -f (Split-Path -Leaf $cfgPath)) -ForegroundColor DarkGray
        }
        $configTouched = $true
    }
    else {
        Write-Host " $(Split-Path -Leaf $cfgPath): no permission object (unchanged)" -ForegroundColor DarkGray
    }
    break  # only one of .jsonc / .json exists
}

if (-not $configTouched -and -not (Test-Path -LiteralPath $jsoncPath) -and -not (Test-Path -LiteralPath $jsonPath)) {
    Write-Host ' .opencode/opencode.json(c) not found — skipping project config' -ForegroundColor DarkGray
}

Write-Host '=== apply-headless-permissions complete ===' -ForegroundColor Green
