#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
    Pester 5 tests for scripts/create-repo-agent-context.ps1 — the agent-context
    launch wrapper — and the Test-OwnerVisibilityPolicy helper it enforces.

.DESCRIPTION
    Covers the wrapper's contract:

      * Test-OwnerVisibilityPolicy truth table (pure function, dot-sourced).
      * The entry-point parameter surface (types, defaults, ValidateSet / Alias /
        ValidatePattern attributes) read from Get-Command metadata and the
        PowerShell AST — not from a text match on the source file.
      * The owner/visibility policy guard and the plan-docs guard, exercised end
        to end out of process.
      * That -PlanDocsRoot actually redirects plan-docs resolution, and that the
        policy guard runs BEFORE the plan-docs guard.
      * The -Help and missing -Slug early exits.

    SAFETY — stage 1 (create-repo-with-plan-docs.ps1) shells out to git/gh
    and creates directories under ../dynamic_workflows. The
    guard order in the wrapper is (a) -Help -> exit 0, (b) blank -Slug -> exit 1,
    (c) policy guard throw, (d) plan-docs guard throw, and only then stage 1.
    Every out-of-process invocation below is deliberately built to stop at (a),
    (b), (c) or (d); none combines an existing slug WITH a policy-passing
    owner/visibility pair, so no test can reach stage 1. Do not "tidy up" an
    invocation into a passing combination — that would launch real repo creation.

    MESSAGE MATCHING — a top-level `throw` in a script reaches us already
    rendered by PowerShell's exception formatter, which soft-wraps the message at
    the console width and prefixes every continuation line with '| '. A
    contiguous substring match on the raw captured text is therefore
    terminal-width dependent. Get-MessageText drops those break markers and all
    whitespace from both the haystack and the expected substring, so a message is
    compared as text rather than as however the terminal happened to break lines.
    Needles contain no '|', so they are unaffected.

    The guards use top-level throw/exit, so they are exercised in a child pwsh;
    an in-process call would unwind into Pester itself and abort the run.

    Run: pwsh -NoProfile -Command "Invoke-Pester -Path ./tests -Output Detailed"
#>

BeforeAll {
    # Pure helper — see the MESSAGE MATCHING note above. Defined first because
    # the normalised message constants below go through it.
    function Get-MessageText {
        param([string]$Text)
        if ([string]::IsNullOrEmpty($Text)) { return '' }
        $unwrapped = $Text -replace '(?m)^\s*\|\s*', ''
        return ($unwrapped -replace '\s', '')
    }

    # One BeforeAll per block, and this container-level one is the only place
    # shared paths come from (Pester 5 gotcha: a second BeforeAll in the same
    # Describe silently nulls $script: vars for the whole block).
    $script:EntryPoint = (Resolve-Path (Join-Path $PSScriptRoot '..' 'scripts' 'create-repo-agent-context.ps1')).Path
    $script:CreateRepoScript = (Resolve-Path (Join-Path $PSScriptRoot '..' 'scripts' 'create-repo-with-plan-docs.ps1')).Path
    $script:RepoFunctions = (Resolve-Path (Join-Path $PSScriptRoot '..' 'scripts' 'repo-functions.ps1')).Path

    # Clones land beside the repository. The entry point resolves the parent from
    # scripts/ as two levels up; tests/ sits at the same depth, so this mirrors
    # the script's own $CloneParentDir exactly.
    $script:CloneParentDir = Join-Path $PSScriptRoot '..' '..' 'dynamic_workflows'

    # The wrapper's default -PlanDocsRoot is
    # Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs' relative
    # to scripts/ — the same <parent-of-repo> anchor this file resolves to.
    $script:DefaultPlanDocsRoot = Join-Path $PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs'

    # Stable substrings of the two guard messages, pre-normalised so every
    # assertion compares against the same form applied to the captured output.
    $script:PolicyMessage = Get-MessageText "Invalid owner/visibility combination: 'nam20485/private'. Private repos are only supported under the 'intel-agency' owner"
    $script:PlanDocsMessage = Get-MessageText 'Plan docs directory not found'
}

Describe 'Test-OwnerVisibilityPolicy' {
    BeforeAll {
        # Pure function, so it is called directly in-process after dot-sourcing
        # the helper file (no side effects in repo-functions.ps1).
        . $script:RepoFunctions
    }

    It 'allows a private repo under the intel-agency owner' {
        Test-OwnerVisibilityPolicy -Owner 'intel-agency' -Visibility 'private' | Should -BeTrue
    }

    It 'allows a public repo under the intel-agency owner' {
        Test-OwnerVisibilityPolicy -Owner 'intel-agency' -Visibility 'public' | Should -BeTrue
    }

    It 'allows a public repo under any other owner' {
        Test-OwnerVisibilityPolicy -Owner 'nam20485' -Visibility 'public' | Should -BeTrue
    }

    It 'rejects a private repo under a non-intel-agency owner' {
        Test-OwnerVisibilityPolicy -Owner 'nam20485' -Visibility 'private' | Should -BeFalse
    }

    It 'treats the owner name case-insensitively' {
        # Intended behaviour, not a bug to "fix" in scripts/: -eq on strings is
        # case-insensitive in PowerShell and GitHub logins are case-insensitive,
        # so 'Intel-Agency' names the same Enterprise organisation and must get
        # the same private-repo allowance.
        Test-OwnerVisibilityPolicy -Owner 'Intel-Agency' -Visibility 'private' | Should -BeTrue
    }

    It 'throws instead of returning when -Owner is an empty string' {
        # Intended behaviour, not a bug to "fix" in scripts/: both parameters are
        # [Parameter(Mandatory)][string] with no [AllowEmptyString()], and
        # PowerShell refuses to bind an empty string to a Mandatory string
        # parameter. The call therefore raises a parameter-binding error (its
        # message contains "empty string") — the boolean expression is never
        # evaluated and $true is never returned.
        { Test-OwnerVisibilityPolicy -Owner '' -Visibility 'public' } | Should -Throw '*empty string*'
    }
}

Describe 'create-repo-agent-context.ps1 parameter surface' {
    BeforeAll {
        $script:Cmd = Get-Command -Name $script:EntryPoint

        $tokens = $null
        $parseErrors = $null
        $script:Ast = [System.Management.Automation.Language.Parser]::ParseFile(
            $script:EntryPoint, [ref]$tokens, [ref]$parseErrors)
        $script:ParseErrors = @($parseErrors)

        $paramBlock = $script:Ast.FindAll({
                param($node) $node -is [System.Management.Automation.Language.ParamBlockAst]
            }, $true) | Select-Object -First 1

        $script:AstParams = @{}
        foreach ($parameterAst in $paramBlock.Parameters) {
            $script:AstParams[$parameterAst.Name.VariablePath.UserPath] = $parameterAst
        }
    }

    It 'parses cleanly and declares the whole ten-parameter surface' {
        $script:ParseErrors | Should -BeNullOrEmpty
        @($script:AstParams.Keys).Count | Should -Be 10
        foreach ($name in @('Slug', 'PlanDocsRoot', 'Owner', 'Visibility', 'Count',
                            'Yes', 'LaunchEditor', 'TriggerHierarchyInit', 'DryRun', 'Help')) {
            $script:Cmd.Parameters.ContainsKey($name) | Should -BeTrue -Because "-$name is part of the entry-point contract"
        }
    }

    It 'exposes -PlanDocsRoot as a string parameter' {
        $script:Cmd.Parameters.ContainsKey('PlanDocsRoot') | Should -BeTrue
        $script:Cmd.Parameters['PlanDocsRoot'].ParameterType | Should -Be ([string])
    }

    It 'types the launch parameters' {
        $script:Cmd.Parameters['Count'].ParameterType | Should -Be ([int])
        # -TriggerHierarchyInit is a real [bool] (it defaults to $true and is
        # branched on with $false), not a switch.
        $script:Cmd.Parameters['TriggerHierarchyInit'].ParameterType | Should -Be ([bool])
        $script:Cmd.Parameters['Yes'].ParameterType | Should -Be ([switch])
        $script:Cmd.Parameters['DryRun'].ParameterType | Should -Be ([switch])
    }

    It 'declares -Slug as optional but pattern-constrained' {
        $script:Cmd.Parameters['Slug'].ParameterType | Should -Be ([string])

        # Optional on purpose: a blank -Slug must reach the friendly
        # 'Error: -Slug is required.' path (covered in the early-exits Describe)
        # and -Help must stay usable without it. Read off the AST
        # [Parameter(...)] attribute's named arguments, not off source text.
        $parameterAttribute = @($script:AstParams['Slug'].Attributes) |
            Where-Object { $_ -is [System.Management.Automation.Language.AttributeAst] -and $_.TypeName.Name -eq 'Parameter' } |
            Select-Object -First 1
        $null -ne $parameterAttribute | Should -BeTrue
        @($parameterAttribute.NamedArguments | ForEach-Object { $_.Name.VariablePath.UserPath }) | Should -Not -Contain 'Mandatory'

        $pattern = @($script:AstParams['Slug'].Attributes) |
            Where-Object { $_ -is [System.Management.Automation.Language.AttributeAst] -and $_.TypeName.Name -eq 'ValidatePattern' } |
            Select-Object -First 1
        $null -ne $pattern | Should -BeTrue -Because 'a slug becomes a repo name, so it stays character-constrained'
        @($pattern.PositionalArguments)[0].Value | Should -Be '^[A-Za-z0-9_.-]+$'
    }

    It 'constrains -Visibility to exactly public and private' {
        $script:Cmd.Parameters.ContainsKey('Visibility') | Should -BeTrue
        $script:Cmd.Parameters['Visibility'].ParameterType | Should -Be ([string])

        $validateSet = @($script:AstParams['Visibility'].Attributes) |
            Where-Object { $_ -is [System.Management.Automation.Language.AttributeAst] -and $_.TypeName.Name -eq 'ValidateSet' } |
            Select-Object -First 1
        $null -ne $validateSet | Should -BeTrue -Because 'the accepted visibilities must stay an explicit pair'

        # The [ValidateSet(...)] attribute's own positional arguments — the
        # exact accepted set, in source order.
        $allowed = @($validateSet.PositionalArguments | ForEach-Object { $_.Value })
        $allowed | Should -Be @('public', 'private')
    }

    It 'defaults -Owner to exactly intel-agency' {
        # ParameterAst.DefaultValue is the AST node of the initialiser, not an
        # evaluated object, so this pins the literal written in the param block.
        $default = $script:AstParams['Owner'].DefaultValue
        $default | Should -BeOfType ([System.Management.Automation.Language.StringConstantExpressionAst])
        $default.Value | Should -Be 'intel-agency'
    }

    It 'defaults -TriggerHierarchyInit to $true' {
        $default = $script:AstParams['TriggerHierarchyInit'].DefaultValue
        $default | Should -BeOfType ([System.Management.Automation.Language.VariableExpressionAst])
        # Comparing the initialiser's source text stops `1` or `[bool]1` from
        # quietly satisfying the assertion.
        $default.Extent.Text | Should -Be '$true'
    }

    It 'defaults -Visibility to public and -Count to 1' {
        $script:AstParams['Visibility'].DefaultValue.Value | Should -Be 'public'
        $script:AstParams['Count'].DefaultValue.Value | Should -Be 1
    }

    It 'declares -Help with the h alias' {
        $script:Cmd.Parameters['Help'].ParameterType | Should -Be ([switch])
        @($script:Cmd.Parameters['Help'].Aliases) | Should -Contain 'h'

        $aliasAst = @($script:AstParams['Help'].Attributes) |
            Where-Object { $_ -is [System.Management.Automation.Language.AttributeAst] -and $_.TypeName.Name -eq 'Alias' } |
            Select-Object -First 1
        @($aliasAst.PositionalArguments | ForEach-Object { $_.Value }) | Should -Be @('h')
    }

    It 'anchors the default -PlanDocsRoot at the sibling workflow-launch2 store' {
        # Exact initialiser, normalised on both sides so a re-format cannot
        # break it. This is what makes the existence check in the
        # 'default -PlanDocsRoot' Describe mirror the script rather than test an
        # unrelated path.
        $expected = Get-MessageText "(Join-Path `$PSScriptRoot '..' '..' 'workflow-launch2' 'plan_docs')"
        (Get-MessageText $script:AstParams['PlanDocsRoot'].DefaultValue.Extent.Text) | Should -Be $expected
    }
}

Describe 'create-repo-with-plan-docs.ps1 retired parameters' {
    BeforeAll {
        $script:CreateRepoCmd = Get-Command -Name $script:CreateRepoScript
    }

    It 'no longer exposes -TriggerProjectSetup' {
        # Regression guard: the legacy project-setup path was deleted in the
        # fold; the agent-context wrapper never passes it.
        $script:CreateRepoCmd.Parameters.ContainsKey('TriggerProjectSetup') | Should -BeFalse
        @($script:CreateRepoCmd.Parameters.Keys) | Should -Not -Contain 'TriggerProjectSetup' -Because 'project-setup triggering was retired'
    }

    It 'no longer exposes -SkipProjectSetup' {
        $script:CreateRepoCmd.Parameters.ContainsKey('SkipProjectSetup') | Should -BeFalse
        @($script:CreateRepoCmd.Parameters.Keys) | Should -Not -Contain 'SkipProjectSetup' -Because 'project-setup triggering was retired'
    }
}

Describe 'create-repo-agent-context.ps1 policy guard (end to end)' {
    BeforeAll {
        $script:CloneParentExisted = Test-Path -LiteralPath $script:CloneParentDir
        $script:BeforeNames = @()
        $script:AfterNames = @()
        if ($script:CloneParentExisted) {
            $script:BeforeNames = @(Get-ChildItem -LiteralPath $script:CloneParentDir -Directory -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Name } | Sort-Object)
        }

        # Out of process: the guard is a top-level throw. 2>&1 folds the
        # rendered error record into the captured stream, and $LASTEXITCODE is
        # read on the very next statement so nothing can clobber it.
        $script:GuardOutput = & pwsh -NoProfile -File $script:EntryPoint `
            -Slug any-slug -Owner nam20485 -Visibility private -DryRun -Yes 2>&1 | Out-String
        $script:GuardExitCode = $LASTEXITCODE

        if ($script:CloneParentExisted) {
            $script:AfterNames = @(Get-ChildItem -LiteralPath $script:CloneParentDir -Directory -ErrorAction SilentlyContinue |
                ForEach-Object { $_.Name } | Sort-Object)
        }
    }

    It 'bails out non-zero on a rejected owner/visibility combination' {
        # Typed first: $null would sneak past -Not -Be 0, so pin that the child
        # process really reported an exit code.
        $script:GuardExitCode | Should -BeOfType ([int])
        $script:GuardExitCode | Should -Not -Be 0 -Because 'a policy violation must abort the launch'
    }

    It 'prints the owner/visibility policy message' {
        (Get-MessageText $script:GuardOutput) | Should -BeLike "*$($script:PolicyMessage)*"
    }

    It 'throws before stage 1 can create a clone directory' {
        if (-not $script:CloneParentExisted) {
            Set-ItResult -Skipped -Because "the sibling clone parent $script:CloneParentDir is absent in this checkout, so there is nothing to compare"
        }
        @($script:AfterNames).Count | Should -Be @($script:BeforeNames).Count
        ($script:AfterNames -join [Environment]::NewLine) |
            Should -Be ($script:BeforeNames -join [Environment]::NewLine) -Because 'the policy guard runs before create-repo-with-plan-docs.ps1'
    }
}

Describe 'create-repo-agent-context.ps1 plan-docs guard (end to end)' {
    BeforeAll {
        # The default owner (intel-agency) passes the policy guard, so this
        # delivery reaches the plan-docs guard — and stops there, because the
        # slug does not exist in the default store.
        $script:GuardOutput = & pwsh -NoProfile -File $script:EntryPoint `
            -Slug no-such-slug-xyz -Visibility public -DryRun -Yes 2>&1 | Out-String
        $script:GuardExitCode = $LASTEXITCODE
    }

    It 'bails out non-zero for an unknown slug' {
        $script:GuardExitCode | Should -BeOfType ([int])
        $script:GuardExitCode | Should -Not -Be 0 -Because 'an unknown slug cannot be launched'
    }

    It 'names the missing slug in the message' {
        $expected = Get-MessageText "Plan docs directory not found for slug 'no-such-slug-xyz':"
        (Get-MessageText $script:GuardOutput) | Should -BeLike "*$expected*"
    }

    It 'tells the reader about -PlanDocsRoot in the same message' {
        (Get-MessageText $script:GuardOutput) | Should -BeLike '*-PlanDocsRoot*' -Because 'the hint must say how to point at another store'
    }
}

Describe 'create-repo-agent-context.ps1 default -PlanDocsRoot' {
    It 'resolves to the sibling workflow-launch2 plan_docs store when that checkout is present' {
        if (-not (Test-Path -LiteralPath $script:DefaultPlanDocsRoot)) {
            # CI clones this repository alone; the launcher checkout is a sibling
            # that only exists where workflow-launch2 was cloned too.
            Set-ItResult -Skipped -Because "the sibling launcher checkout $script:DefaultPlanDocsRoot is not present in this environment"
        }
        (Test-Path -LiteralPath $script:DefaultPlanDocsRoot -PathType Container) | Should -BeTrue
    }
}

Describe 'create-repo-agent-context.ps1 -PlanDocsRoot override' {
    Context 'policy guard takes precedence over the plan-docs guard' {
        BeforeAll {
            # A root that DOES hold the slug, paired with a rejected
            # owner/visibility combination.
            $script:SlugRoot = Join-Path $TestDrive 'policy-precedence'
            $script:SlugName = 'probe-slug-abc'
            New-Item -ItemType Directory -Path (Join-Path $script:SlugRoot $script:SlugName) -Force | Out-Null
            Set-Content -LiteralPath (Join-Path (Join-Path $script:SlugRoot $script:SlugName) 'one.md') -Value '# probe'
            (Test-Path -LiteralPath (Join-Path $script:SlugRoot $script:SlugName) -PathType Container) | Should -BeTrue

            $script:GuardOutput = & pwsh -NoProfile -File $script:EntryPoint `
                -PlanDocsRoot $script:SlugRoot -Slug $script:SlugName `
                -Owner nam20485 -Visibility private -DryRun -Yes 2>&1 | Out-String
            $script:GuardExitCode = $LASTEXITCODE
        }

        It 'throws the POLICY message even though the plan docs exist' {
            # This proves the guard ORDERING only — that the override itself is
            # honoured is shown by the sibling Context below, where the policy
            # passes and the plan-docs guard is reached.
            $script:GuardExitCode | Should -BeOfType ([int])
            $script:GuardExitCode | Should -Not -Be 0
            $compact = Get-MessageText $script:GuardOutput
            $compact | Should -BeLike "*$($script:PolicyMessage)*"
            $compact | Should -Not -BeLike "*$($script:PlanDocsMessage)*" -Because 'the plan-docs guard is never reached once the policy guard throws'
        }
    }

    Context 'the override redirects resolution away from the default root' {
        BeforeAll {
            # A root that does NOT hold the slug, with the sanctioned
            # intel-agency owner so the policy guard passes and the plan-docs
            # guard is the one that fires. If -PlanDocsRoot were ignored, the
            # message would name the default workflow-launch2 path instead.
            $script:EmptyRoot = Join-Path $TestDrive 'empty-root'
            New-Item -ItemType Directory -Path $script:EmptyRoot -Force | Out-Null
            (Test-Path -LiteralPath (Join-Path $script:EmptyRoot 'probe-slug-xyz')) | Should -BeFalse

            $script:GuardOutput = & pwsh -NoProfile -File $script:EntryPoint `
                -PlanDocsRoot $script:EmptyRoot -Slug probe-slug-xyz `
                -Owner intel-agency -Visibility private -DryRun -Yes 2>&1 | Out-String
            $script:GuardExitCode = $LASTEXITCODE
        }

        It 'bails out non-zero at the plan-docs guard, never reaching stage 1' {
            $script:GuardExitCode | Should -BeOfType ([int])
            $script:GuardExitCode | Should -Not -Be 0
            $expected = Get-MessageText "Plan docs directory not found for slug 'probe-slug-xyz':"
            (Get-MessageText $script:GuardOutput) | Should -BeLike "*$expected*"
        }

        It 'reports the override root, not the default workflow-launch2 root' {
            $compact = Get-MessageText $script:GuardOutput

            $root = Get-MessageText $script:EmptyRoot
            $compact | Should -BeLike "*$root*" -Because '-PlanDocsRoot must drive the resolved source directory'

            $defaultTail = Get-MessageText (Join-Path (Join-Path 'workflow-launch2' 'plan_docs') 'probe-slug-xyz')
            $compact | Should -Not -BeLike "*$defaultTail*" -Because 'the default store must not be consulted once -PlanDocsRoot is given'
        }
    }
}

Describe 'create-repo-agent-context.ps1 early exits' {
    BeforeAll {
        # Neither path can reach stage 1: -Help exits 0 before both guards, and
        # the blank-slug branch exits 1 right after it.
        $script:HelpOutput = & pwsh -NoProfile -File $script:EntryPoint -Help 2>&1 | Out-String
        $script:HelpExitCode = $LASTEXITCODE

        $script:NoSlugOutput = & pwsh -NoProfile -File $script:EntryPoint -DryRun 2>&1 | Out-String
        $script:NoSlugExitCode = $LASTEXITCODE
    }

    It '-Help prints the usage block and exits 0' {
        $script:HelpExitCode | Should -Be 0 -Because '-Help is a normal termination'
        (Get-MessageText $script:HelpOutput) | Should -BeLike ('*' + (Get-MessageText 'create-repo-agent-context') + '*') -Because 'usage must name the script'
    }

    It 'omitting -Slug exits non-zero and reports -Slug is required' {
        $script:NoSlugExitCode | Should -Not -Be 0
        (Get-MessageText $script:NoSlugOutput) | Should -BeLike ('*' + (Get-MessageText 'Error: -Slug is required.') + '*') -Because 'the script must say which parameter is missing'
    }
}

Describe 'create-repo-agent-context.ps1 seed-commit push' {
    BeforeAll {
        # Static contract only — executing the amend/push path would need the
        # full git/gh pipeline, forbidden by the SAFETY note at the top of this
        # file. The AST is what the 'parameter surface' Describe already uses.
        $parseErrors = $null
        $script:WrapperAst = [System.Management.Automation.Language.Parser]::ParseFile($script:EntryPoint, [ref]$null, [ref]$parseErrors)
        $parseErrors | Should -BeNullOrEmpty
    }

    It 'force-pushes the amended seed commit inside the same non-DryRun guard' {
        $guards = @($script:WrapperAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Extent.Text -match 'commit\s+--amend\s+--no-edit'
        }, $true))
        $guards.Count | Should -Be 1 -Because 'the wrapper amends the seed commit exactly once'
        $guards[0].Extent.Text | Should -Match '-not\s+\$\s*DryRun' -Because 'a dry run must amend nothing'
        $guards[0].Extent.Text | Should -Match 'git\s+push\s+--force-with-lease\s+origin\s+HEAD\s' -Because 'the amended seed commit must reach the branch stage 1 pushed (the agent-context template default, development — a generated repo has no main), not a hardcoded HEAD:main'
    }

    It 'aborts loudly when the amend or the push fails' {
        $throwTexts = @($script:WrapperAst.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.ThrowStatementAst]
        }, $true) | ForEach-Object { $_.Extent.Text })
        ($throwTexts -join "`n") | Should -Match 'git commit --amend failed' -Because 'a failed amend must stop the pipeline'
        ($throwTexts -join "`n") | Should -Match 'git push --force-with-lease failed' -Because 'an amend that never reaches the remote is the PR #20 defect'
    }
}
