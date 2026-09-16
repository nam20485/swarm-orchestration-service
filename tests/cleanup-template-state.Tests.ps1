#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
    Pester 5 unit tests for cleanup-template-state.ps1
#>

BeforeAll {
    $script:ScriptPath = Join-Path $PSScriptRoot '..' 'scripts' 'cleanup-template-state.ps1'
}

Describe 'cleanup-template-state.ps1' {
    BeforeEach {
        # Build a synthetic freshly-cloned agent-context repo fixture.
        $script:FixtureRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ct-fix-{0}" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Path $script:FixtureRoot | Out-Null

        $agentsDir     = Join-Path $script:FixtureRoot '.agents'
        $completedDir  = Join-Path $script:FixtureRoot 'docs/plans/.completed'
        $deferredDir   = Join-Path $script:FixtureRoot 'docs/plans/.deferred'
        $runReviewDir  = Join-Path $script:FixtureRoot 'docs/plans/.completed/run-issues-review'
        $planDocsDir   = Join-Path $script:FixtureRoot 'plan_docs'
        $plansDir      = Join-Path $script:FixtureRoot 'docs/plans'

        foreach ($d in @($agentsDir, $completedDir, $deferredDir, $runReviewDir, $planDocsDir, $plansDir)) {
            New-Item -ItemType Directory -Path $d -Force | Out-Null
        }

        # Realistic Class-2 content: populated memory, template plans, a leaked run-review.
        Set-Content -LiteralPath (Join-Path $agentsDir 'memory.md') -Value "# Project Memory`n`n## Current Activity`n`n### Project: Template-repo content strategy`n`n- **Some template work item** (2026-07-18): populated."
        Set-Content -LiteralPath (Join-Path $completedDir 'template-strategy-plan.md') -Value 'Template completed plan.'
        Set-Content -LiteralPath (Join-Path $deferredDir 'defect-level-plan.md') -Value 'Template deferred plan.'
        Set-Content -LiteralPath (Join-Path $runReviewDir 'gh-issue-tracking-init-run-review.md') -Value 'Leaked downstream run-review.'
        Set-Content -LiteralPath (Join-Path $planDocsDir 'development-plan.md') -Value 'Clone-seeded primary plan doc.'
        Set-Content -LiteralPath (Join-Path $plansDir 'Modern Linux Alternatives.md') -Value 'Owner plan note (personal).'
        Set-Content -LiteralPath (Join-Path $plansDir 'Ornith & Unsloth Setup Guide for AMD RX 6700 XT.md') -Value 'Owner plan note (personal).'
        Set-Content -LiteralPath (Join-Path $plansDir 'powershell-standard-rules-plan.md') -Value 'Template-self plan.'
        Set-Content -LiteralPath (Join-Path $plansDir 'upstream-issue-body-content-plan.md') -Value 'Template-self plan.'
        Set-Content -LiteralPath (Join-Path $plansDir 'workflow-launch2-clone-pipeline-class2-cleanup.md') -Value 'Template-self plan.'
        Set-Content -LiteralPath (Join-Path $plansDir 'clone-example-active-plan.md') -Value 'Active plan unrelated to cleanup lists — must survive.'
    }

    AfterEach {
        if (Test-Path -LiteralPath $script:FixtureRoot) {
            Remove-Item -LiteralPath $script:FixtureRoot -Recurse -Force
        }
    }

    It 'resets memory.md to the blank skeleton' {
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        $content = Get-Content -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Raw
        $content | Should -Match '^# Project Memory'
        $content | Should -Match '## Current Activity'
        $content | Should -Match '## Completed Work Items'
        $content | Should -Match '## Decisions'
        $content | Should -Match '## Remember To Do'
        # Template-specific content is gone.
        $content | Should -Not -Match 'Template-repo content strategy'
    }

    It 'removes every *.md directly under .completed and .deferred (lifecycle dirs preserved)' {
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        $completedRemaining = @(Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed') -File -Force -Filter '*.md')
        $deferredRemaining  = @(Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.deferred') -File -Force -Filter '*.md')
        $completedRemaining.Count | Should -Be 0
        $deferredRemaining.Count  | Should -Be 0
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed') | Should -BeTrue
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.deferred')  | Should -BeTrue
    }

    It 'removes the run-issues-review subtree entirely' {
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed/run-issues-review') | Should -BeFalse
    }

    It 'removes owner plan notes and template-self plans by name but preserves other active plans' {
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/Modern Linux Alternatives.md') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/Ornith & Unsloth Setup Guide for AMD RX 6700 XT.md') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/powershell-standard-rules-plan.md') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/upstream-issue-body-content-plan.md') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/workflow-launch2-clone-pipeline-class2-cleanup.md') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/clone-example-active-plan.md') | Should -BeTrue
        Get-Content -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/clone-example-active-plan.md') | Should -Match 'must survive'
    }

    It 'is idempotent — running twice is a no-op' {
        # First run populates the skeleton and clears the plans.
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null
        # Overwrite memory with fresh custom content to prove the second run
        # still hits the skeleton branch (not "already skeleton").
        Set-Content -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Value "# Project Memory`n`n## Current Activity`n`nCustom content inserted between runs."

        # Second run — should reset to skeleton again; no errors.
        { & $script:ScriptPath -RepoRoot $script:FixtureRoot } | Should -Not -Throw
        $content = Get-Content -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Raw
        $content | Should -Not -Match 'Custom content inserted between runs'
    }

    It 'preserves clone-seeded plan_docs (not Class-2)' {
        & $script:ScriptPath -RepoRoot $script:FixtureRoot | Out-Null

        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'plan_docs/development-plan.md') | Should -BeTrue
        Get-Content -LiteralPath (Join-Path $script:FixtureRoot 'plan_docs/development-plan.md') | Should -Match 'Clone-seeded primary plan doc'
    }

    It 'skips missing paths without erroring' {
        # Remove all target paths before running.
        Remove-Item -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Force
        Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed') -Force | Remove-Item -Recurse -Force
        Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.deferred')  -Force | Remove-Item -Recurse -Force

        { & $script:ScriptPath -RepoRoot $script:FixtureRoot } | Should -Not -Throw
    }

    It '-DryRun does not modify the filesystem' {
        $beforeMemory    = Get-Content -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Raw
        $beforeCompleted = Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed') -File -Force
        $beforeDeferred  = Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.deferred') -File -Force
        $beforeRunReview = Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed/run-issues-review')

        & $script:ScriptPath -RepoRoot $script:FixtureRoot -DryRun | Out-Null

        Get-Content -LiteralPath (Join-Path $script:FixtureRoot '.agents/memory.md') -Raw | Should -Be $beforeMemory
        Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed') -File -Force | Should -HaveCount $beforeCompleted.Count
        Get-ChildItem -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.deferred') -File -Force | Should -HaveCount $beforeDeferred.Count
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/.completed/run-issues-review') | Should -Be $beforeRunReview
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/Modern Linux Alternatives.md') | Should -BeTrue
        Test-Path -LiteralPath (Join-Path $script:FixtureRoot 'docs/plans/workflow-launch2-clone-pipeline-class2-cleanup.md') | Should -BeTrue
    }

    It 'throws when -RepoRoot does not exist' {
        $bogus = Join-Path ([System.IO.Path]::GetTempPath()) ("does-not-exist-{0}" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
        { & $script:ScriptPath -RepoRoot $bogus } | Should -Throw
    }
}
