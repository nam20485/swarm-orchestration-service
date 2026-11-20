#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
    Pester 5 tests for the clone branch-protection ruleset asset and
    import-ruleset.ps1.

.DESCRIPTION
    The ruleset is the MECHANICAL merge gate (rev2 Decision 14) — these tests
    drift-guard its invariants so a careless edit to the asset fails CI:
    required `validate` check present, EMPTY bypass list, merge-commit-only
    merges, development-branch targeting. The script tests cover parameter
    validation and the DryRun no-network path.
#>

BeforeAll {
    $script:ScriptPath = Join-Path $PSScriptRoot '..' 'scripts' 'import-ruleset.ps1'
    $script:AssetPath = Join-Path $PSScriptRoot '..' '.github' '.clone-ruleset.json'
}

Describe 'clone ruleset asset invariants' {
    BeforeAll {
        $script:Asset = Get-Content -LiteralPath $script:AssetPath -Raw | ConvertFrom-Json -AsHashtable
    }

    It 'is valid JSON with the expected name and active enforcement' {
        $Asset['name'] | Should -Be 'protected branches'
        $Asset['enforcement'] | Should -Be 'active'
        $Asset['target'] | Should -Be 'branch'
    }

    It 'targets the clone default branch (development) only' {
        $Asset['conditions']['ref_name']['include'] | Should -Be @('refs/heads/development')
    }

    It 'requires the validate status check (the CI job running the identical ./validation.ps1)' {
        $checkRule = $Asset['rules'] | Where-Object { $_['type'] -eq 'required_status_checks' }
        $checkRule | Should -Not -BeNullOrEmpty
        # The API field is strict_required_status_checks_policy (with the s) —
        # the misspelling is silently rejected as "data matches no possible input".
        $checkRule['parameters']['strict_required_status_checks_policy'] | Should -BeFalse
        $contexts = @($checkRule['parameters']['required_status_checks'] | ForEach-Object { $_['context'] })
        $contexts | Should -Contain 'validate'
    }

    It 'has an EMPTY bypass list — nobody, including admin tokens, merges around a red gate' {
        # THE invariant (owner 2026-11-20): adding any bypass actor here must
        # be a deliberate, reviewed decision — this test is the speed bump.
        @($Asset['bypass_actors']).Count | Should -Be 0
    }

    It 'allows MERGE-COMMIT merges only (squash and rebase disabled, owner 2026-11-20)' {
        $prRule = $Asset['rules'] | Where-Object { $_['type'] -eq 'pull_request' }
        $prRule | Should -Not -BeNullOrEmpty
        $prRule['parameters']['allowed_merge_methods'] | Should -Be @('merge')
        # zero-threads gate enforced by GitHub too
        $prRule['parameters']['required_review_thread_resolution'] | Should -BeTrue
        # the autonomous cycle merges with zero human approvals by design
        $prRule['parameters']['required_approving_review_count'] | Should -Be 0
    }

    It 'protects history: deletion and non_fast_forward rules present' {
        $types = @($Asset['rules'] | ForEach-Object { $_['type'] })
        $types | Should -Contain 'deletion'
        $types | Should -Contain 'non_fast_forward'
    }

    It 'carries no API-rejected fields (documentation-only keys are stripped by the importer)' {
        # id/source/source_type are UI-export read fields the create API rejects;
        # only the $comment doc key is allowed (and stripped before the call).
        $Asset.Keys | Should -Not -Contain 'id'
        $Asset.Keys | Should -Not -Contain 'source'
        $Asset.Keys | Should -Not -Contain 'source_type'
    }
}

Describe 'import-ruleset.ps1' {
    It 'rejects a malformed -Repo (must be owner/repo)' {
        { & $ScriptPath -Repo 'not-a-repo' -DryRun } | Should -Throw
    }

    It 'throws when the ruleset file is missing' {
        { & $ScriptPath -Repo 'owner/repo' -RulesetFile '/nonexistent/ruleset.json' -DryRun } | Should -Throw
    }

    It 'DryRun reports the required check and makes no network call' {
        $out = (& $ScriptPath -Repo 'example/none' -DryRun *>&1) | Out-String
        $out | Should -Match 'validate'
        $out | Should -Match 'NONE by design'
    }

    It 'DryRun uses the committed asset by default' {
        $out = (& $ScriptPath -Repo 'example/none' -DryRun *>&1) | Out-String
        $out | Should -Match 'protected branches'
    }
}
