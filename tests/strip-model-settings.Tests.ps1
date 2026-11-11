#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
    Pester 5 unit tests for strip-model-settings.ps1 (v2 layout: strip the
    per-tier pins, stamp the root opencode.json dispatch pin).
#>

BeforeAll {
    $script:ScriptPath = Join-Path $PSScriptRoot '..' 'scripts' 'strip-model-settings.ps1'
}

Describe 'strip-model-settings.ps1' {
    BeforeEach {
        $script:FixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sms-fix-{0}" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Path $script:FixtureRoot | Out-Null
    }

    AfterEach {
        if (Test-Path -LiteralPath $script:FixtureRoot) {
            Remove-Item -LiteralPath $script:FixtureRoot -Recurse -Force
        }
    }

    It 'stamps the root opencode.json model pin (v2 layout, O1 default)' {
        $agentsDir = Join-Path $script:FixtureRoot '.opencode/agents'
        New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
        # The template stamps glm-5.2 for interactive clones; dispatched
        # clones must carry the O1 pin after this script runs.
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        @'
{
  "$schema": "https://opencode.ai/config.json",
  "default_agent": "swarm-orchestrator",
  "model": "zai-coding-plan/glm-5.2",
  "small_model": "zai-coding-plan/glm-4.5-air",
  "mcp": {
    "zread": {
      "headers": { "Authorization": "{env:Z_AI_API_KEY}" }
    }
  }
}
'@ | Set-Content -LiteralPath $root -NoNewline

        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        $doc = Get-Content -LiteralPath $root -Raw | ConvertFrom-Json
        $doc.model | Should -Be 'zai-coding-plan/glm-5.3'
        # small_model and everything else ride the template untouched.
        $doc.small_model | Should -Be 'zai-coding-plan/glm-4.5-air'
        $doc.default_agent | Should -Be 'swarm-orchestrator'
        $doc.mcp.zread.headers.Authorization | Should -Be '{env:Z_AI_API_KEY}'
        # Still valid strict JSON (no comma damage).
        { Get-Content -LiteralPath $root -Raw | ConvertFrom-Json } | Should -Not -Throw
    }

    It 'inserts the model pin when the root opencode.json lacks one' {
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        @'
{
  "$schema": "https://opencode.ai/config.json",
  "default_agent": "swarm-orchestrator"
}
'@ | Set-Content -LiteralPath $root -NoNewline

        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        $doc = Get-Content -LiteralPath $root -Raw | ConvertFrom-Json
        $doc.model | Should -Be 'zai-coding-plan/glm-5.3'
        $doc.default_agent | Should -Be 'swarm-orchestrator'
    }

    It 'is idempotent: an already-correct pin is left byte-identical' {
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        $content = @'
{
  "default_agent": "swarm-orchestrator",
  "model": "zai-coding-plan/glm-5.3"
}
'@
        Set-Content -LiteralPath $root -Value $content -NoNewline

        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        Get-Content -LiteralPath $root -Raw | Should -Be $content
    }

    It 'strips agent frontmatter model pins so the stamped root pin prevails' {
        $agentsDir = Join-Path $script:FixtureRoot '.opencode/agents'
        New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        Set-Content -LiteralPath $root -Value ('{' + "`n" + '  "model": "zai-coding-plan/glm-5.2"' + "`n" + '}') -NoNewline
        $agent = Join-Path $agentsDir 'worker.md'
        @'
---
description: a worker
model: zai-coding-plan/glm-5.3-flash
mode: subagent
---

Body text mentioning model: inline that must survive.
'@ | Set-Content -LiteralPath $agent

        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-null

        $frontmatter = (Get-Content -LiteralPath $agent -Raw) -split "\r?\n"
        # No top-level model: line remains between the fences...
        $fenceEnd = ($frontmatter | Select-Object -Skip 1 | ForEach-Object -Begin { $i = 1 } -Process { if ($_ -match '^---\s*$') { $i }; $i++ } | Select-Object -First 1)
        $frontmatter[1..($fenceEnd - 1)] | Where-Object { $_ -match '^model:\s*\S' } | Should -Be @()
        # ...but the body line mentioning model: survives.
        (Get-Content -LiteralPath $agent -Raw) | Should -Match 'Body text mentioning model: inline'
    }

    It 'strips legacy .opencode/opencode.jsonc pins (pre-v2 clones)' {
        $legacyDir = Join-Path $script:FixtureRoot '.opencode'
        New-Item -ItemType Directory -Path $legacyDir -Force | Out-Null
        $legacy = Join-Path $legacyDir 'opencode.jsonc'
        @'
{
  // v1 project config
  "model": "zai-coding-plan/glm-5.2",
  "small_model": "zai-coding-plan/glm-4.5-air",
  "permission": { "websearch": "allow" }
}
'@ | Set-Content -LiteralPath $legacy

        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        (Get-Content -LiteralPath $legacy -Raw) | Should -Not -Match '"model"'
        (Get-Content -LiteralPath $legacy -Raw) | Should -Not -Match '"small_model"'
        (Get-Content -LiteralPath $legacy -Raw) | Should -Match '"websearch"'
    }

    It 'reports (and leaves) a clone with no root opencode.json' {
        $out = (& $script:ScriptPath -RepoRoot $script:FixtureRoot *>&1) | Out-String
        $out | Should -Match 'pre-v2-template clone'
        (Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'opencode.json')) | Should -BeFalse
    }

    It '-DryRun plans the stamp without touching the filesystem' {
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        $content = '{' + "`n" + '  "model": "zai-coding-plan/glm-5.2"' + "`n" + '}'
        Set-Content -LiteralPath $root -Value $content -NoNewline

        $out = (& $script:ScriptPath -RepoRoot $script:FixtureRoot -DryRun *>&1) | Out-String

        $out | Should -Match 'would stamp model'
        Get-Content -LiteralPath $root -Raw | Should -Be $content
    }

    It 'honors an explicit -PinModel override' {
        $root = Join-Path $script:FixtureRoot 'opencode.json'
        Set-Content -LiteralPath $root -Value ('{' + "`n" + '  "model": "old"' + "`n" + '}') -NoNewline

        & $script:ScriptPath -RepoRoot $script:FixtureRoot -PinModel 'zai-coding-plan/glm-5.4' | Out-Null

        (Get-Content -LiteralPath $root -Raw | ConvertFrom-Json).model | Should -Be 'zai-coding-plan/glm-5.4'
    }
}
