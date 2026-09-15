#!/usr/bin/env pwsh
#requires -Version 7.0

<#
.SYNOPSIS
Create a new GitHub repository with a random suffix, clone it locally, copy plan docs into plan_docs/, commit, and push.

.DESCRIPTION
This script creates one or more repositories named <RepoName>-<randomSuffix> (with letter suffixes when requested)
under the specified owner, clones each to the given destination directory, copies the contents of a plan docs directory
into a docs folder inside each repo, then commits and pushes the changes. It follows PowerShell best practices: approved
verbs, proper parameter validation, non-interactive design, and optional DryRun with ShouldProcess confirmation gating for
remote mutations.

.PARAMETER RepoName
Base repository name (prefix). A random suffix is appended to form the final repo name.

.PARAMETER Owner
GitHub organization or user that will own the repository. Default: intel-agency

.PARAMETER PlanDocsDir
Path to the directory containing plan docs to copy into the new repo's plan_docs/ folder.

.PARAMETER CloneParentDir
Path to the local parent directory where the repository will be cloned (final path will be <CloneParentDir>\<FullRepoName>).

.PARAMETER Visibility
Repository visibility. Must be 'public' or 'private'.

.PARAMETER DryRun
Simulate remote operations (repo create, git push) and local file copies without making changes. Logs actions only.

.PARAMETER Yes
Non-interactive mode. Assume 'yes' for the create confirmation and do not prompt. The editor will only be launched if -LaunchEditor is also provided.

.PARAMETER LaunchEditor
Launch editor with workspace from new repo after creation

.PARAMETER EditorProfile
VS Code profile to use when launching the editor. Default: .NET Stripped

.PARAMETER Count
Number of repositories to create from the specified slug and plan docs. Letter suffixes are appended to the repo names when more than one repo is requested.

.PARAMETER TemplateRepoName
Template repository name used to create new repos and to substitute template placeholders. Default: ai-new-workflow-app-template

.PARAMETER TemplateOwner
Template repository owner used to create new repos and to substitute template owner references (e.g. in image/registry paths). Default: intel-agency

.PARAMETER Help
    Show this usage information and exit. Alias: -h.

.EXAMPLE
./scripts/create-repo-with-plan-docs.ps1 -RepoName planning -PlanDocsDir .\plan_docs\advanced_memory -CloneParentDir .\dynamic_workflows -Visibility public -DryRun -Verbose

.EXAMPLE
./scripts/create-repo-with-plan-docs.ps1 -RepoName planning -PlanDocsDir E:\plan_docs -CloneParentDir E:\work\dynamic_workflows -Owner myorg -Visibility private

.OUTPUTS
System.String. The absolute clone destination path of the created repository.

.NOTES
Requires GitHub CLI (`gh`) and Git. Authenticate with `gh auth login` before running.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium', DefaultParameterSetName = 'Create')]
param(
    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Base repository name (prefix).')]
    [Parameter(ParameterSetName = 'ReplaceOnly', HelpMessage = 'Final repository name to substitute for the template placeholder.')]
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$RepoName,

    [Parameter(ParameterSetName = 'Create')]
    [ValidateNotNullOrEmpty()]
    [string]$Owner = 'intel-agency',

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Directory containing plan docs to copy.')]
    [ValidateNotNullOrEmpty()]
    [string]$PlanDocsDir,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Parent directory to clone into.')]
    [ValidateNotNullOrEmpty()]
    [string]$CloneParentDir,

    [Parameter(ParameterSetName = 'ReplaceOnly', HelpMessage = 'Existing repository root to update and validate locally.')]
    [ValidateNotNullOrEmpty()]
    [string]$ExistingRepoRoot,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Repository visibility: public or private')]
    [ValidateSet('public', 'private')]
    [string]$Visibility = 'public',

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Dry run, don''t make any changes.')]
    [Parameter(ParameterSetName = 'ReplaceOnly', HelpMessage = 'Dry run, don''t make any changes.')]
    [switch]$DryRun,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Assume yes for all prompts')]
    [switch]$Yes,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Launch editor with workspace from new repo after creation')]
    [switch]$LaunchEditor,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'VS Code profile to use when launching the editor.')]
    [string]$EditorProfile = '.NET (Stripped)',

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Trigger the project-setup workflow on the new repo after creation.')]
    [bool]$TriggerProjectSetup = $true,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Skip the legacy project-setup trigger at the end of creation. Intended for callers that invoke trigger-gh-issue-tracking-init.ps1 as a separate step (e.g. create-repo-agent-context.ps1). Default behavior identical.')]
    [switch]$SkipProjectSetup,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'How many repositories to create from the slug and plan docs.')]
    [ValidateScript({ $_ -ge 1 })]
    [int]$Count = 1,

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Template repository name used for new repos.')]
    [Parameter(ParameterSetName = 'ReplaceOnly', HelpMessage = 'Template repository name used for placeholder replacement.')]
    [ValidateNotNullOrEmpty()]
    [string]$TemplateRepoName = 'ai-new-workflow-app-template',

    [Parameter(ParameterSetName = 'Create', HelpMessage = 'Template repository owner used for new repos.')]
    [Parameter(ParameterSetName = 'ReplaceOnly', HelpMessage = 'Template repository owner used for placeholder replacement.')]
    [ValidateNotNullOrEmpty()]
    [string]$TemplateOwner = 'intel-agency',

    [Parameter()]
    [Alias('h')]
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

function Show-Usage {
    Get-Help -Name $PSCommandPath -Detailed | Out-String | Write-Host
}

if ($Help) {
    Show-Usage
    exit 0
}

# Required parameters per parameter set (validated manually so -Help works
# without triggering mandatory-parameter prompts).
$missingParams = @()
if ($PSCmdlet.ParameterSetName -eq 'ReplaceOnly') {
    if ([string]::IsNullOrWhiteSpace($RepoName))        { $missingParams += '-RepoName' }
    if ([string]::IsNullOrWhiteSpace($ExistingRepoRoot)) { $missingParams += '-ExistingRepoRoot' }
}
else {
    if ([string]::IsNullOrWhiteSpace($RepoName))       { $missingParams += '-RepoName' }
    if ([string]::IsNullOrWhiteSpace($PlanDocsDir))    { $missingParams += '-PlanDocsDir' }
    if ([string]::IsNullOrWhiteSpace($CloneParentDir)) { $missingParams += '-CloneParentDir' }
}
if ($missingParams.Count -gt 0) {
    Write-Host "Error: missing required parameter(s) for the '$($PSCmdlet.ParameterSetName)' parameter set: $($missingParams -join ', ')" -ForegroundColor Red
    Write-Host ''
    Show-Usage
    exit 1
}

Write-Host '=== create-repo-with-plan-docs ===' -ForegroundColor Cyan
if ($DryRun) { Write-Host '[DRY-RUN MODE]' -ForegroundColor Yellow }

# Dot-source shared helper functions
Write-Host 'Loading modules...' -ForegroundColor DarkGray -NoNewline
$repoFunctions = Join-Path $PSScriptRoot 'repo-functions.ps1'
if (Test-Path -LiteralPath $repoFunctions) { . $repoFunctions } else { throw "Required file not found: $repoFunctions" }

# Dot-source common auth helper
$commonAuth = Join-Path $PSScriptRoot 'common-auth.ps1'
if (Test-Path -LiteralPath $commonAuth) { . $commonAuth } else { Write-Verbose 'common-auth.ps1 not found; proceeding without dot-sourcing' }

# Dot-source structured logging module
$loggingModule = Join-Path $PSScriptRoot 'logging.ps1'
if (Test-Path -LiteralPath $loggingModule) { . $loggingModule } else { Write-Verbose 'logging.ps1 not found; proceeding without structured logging' }
Write-Host ' done' -ForegroundColor DarkGray

$docsDir = 'plan_docs'

#
# Main execution
#

try {
    # Start structured run log
    if (Get-Command Start-RunLog -ErrorAction SilentlyContinue) {
        $logPath = Start-RunLog -RunName 'create-repo'
        Write-Verbose "Run log: $logPath"
    }

    if ($PSCmdlet.ParameterSetName -eq 'ReplaceOnly') {
        Write-Host "Replacing placeholders in existing repo '$ExistingRepoRoot'..." -ForegroundColor Cyan -NoNewline
        $resolvedRepoRoot = (Resolve-Path -LiteralPath $ExistingRepoRoot).Path
        Update-TemplatePlaceholders -RepoRoot $resolvedRepoRoot -TemplateText $TemplateRepoName -ReplacementText $RepoName
        Assert-NoTemplatePlaceholdersRemaining -RepoRoot $resolvedRepoRoot -TemplateText $TemplateRepoName
        Write-Host ' done' -ForegroundColor Green
        Write-Output "SUCCESS: template placeholders replaced and validated in '$resolvedRepoRoot'"
        return
    }

    # Derive the owner to use for image/registry references
    $TemplateOwnerLower = $TemplateOwner.ToLower()

    # Preconditions
    Write-Host 'Checking prerequisites...' -ForegroundColor Cyan -NoNewline
    Test-ToolExists 'git'
    Test-ToolExists 'gh'
    Write-Host ' done' -ForegroundColor Green

    Write-Host 'Authenticating with GitHub...' -ForegroundColor Cyan -NoNewline
    if (Get-Command Initialize-GitHubAuth -ErrorAction SilentlyContinue) { Initialize-GitHubAuth -DryRun:$DryRun } else {
        # Fallback local check if helper not available
        $st = Invoke-External -FilePath 'gh' -ArgumentList @('auth', 'status') -AllowFail
        if ($st.ExitCode -ne 0) {
            Write-Verbose 'GitHub CLI not authenticated. Initiating gh auth login...'
            if ($DryRun) { Write-Warning '[dry-run] Would run: gh auth login' } else { Invoke-External -FilePath 'gh' -ArgumentList @('auth', 'login') | Out-Null }
        }
    }
    Write-Host ' done' -ForegroundColor Green

    # Determine final repo names (ensure not colliding; try up to 5 suffixes)
    Write-Host 'Resolving repo names...' -ForegroundColor Cyan -NoNewline
    $repoNames = @()
    for ($i = 0; $i -lt 5 -and -not $repoNames; $i++) {
        $suffix = Get-RandomSuffix
        $candidates = Get-RepoNamesForSuffix -RepoName $RepoName -Suffix $suffix -Count $Count
        $collision = $false
        foreach ($candidate in $candidates) {
            if (Test-RepoExists -Owner $Owner -Name $candidate) {
                $collision = $true
                break
            }
        }
        if (-not $collision) {
            $repoNames = @($candidates)
        }
    }
    if (-not $repoNames) { throw "Unable to find an available set of repo names after multiple attempts for base '$RepoName'" }
    Write-Host " $($repoNames -join ', ')" -ForegroundColor Green

    Write-Host ''
    if (-not $Yes) {
        if ($Count -gt 1) {
            $confirm = Read-Host "You have specified to create $Count repos from the $RepoName plans. Are you sure? (y/N):"
            if (($confirm ?? '').Trim().ToLower() -ne 'y') { throw 'User aborted' }
        }
        else {
            Write-Host "Ready to create repository: $Owner/$($repoNames[0])" -ForegroundColor Cyan
            Write-Host "Plan docs source: $PlanDocsDir" -ForegroundColor DarkGray
            Write-Host "Clone destination parent: $CloneParentDir" -ForegroundColor DarkGray
            $continue = Read-Host 'Proceed? (y/N)'
            $continueNorm = ($continue ?? '').Trim().ToLower()
            if ($continueNorm -ne 'y') { throw 'User aborted' }
        }
    }
    else {
        Write-Verbose '-Yes specified: proceeding without confirmation'
    }

    Write-Verbose "Chosen repository names: $($repoNames -join ', ')"

    $lastEditorTarget = $null
    foreach ($repoName in $repoNames) {
        Write-Verbose "Creating repository: $Owner/$repoName"
        if (Get-Command Write-RunLog -ErrorAction SilentlyContinue) { Write-RunLog -Level 'INFO' -Step 'create-repo' -Message "Creating $Owner/$repoName" -Data @{ owner = $Owner; repoName = $repoName; visibility = $Visibility } }

        # Create repository
        Write-Host "Creating repository '$Owner/$repoName'..." -ForegroundColor Cyan -NoNewline
        New-GitHubRepository -Owner $Owner -Name $repoName -Visibility $Visibility -Template "$TemplateOwner/$TemplateRepoName"
        Write-Host ' done' -ForegroundColor Green

        # Poll GitHub API until the template's initial commit exists on the default branch.
        Write-Host 'Waiting for template initialization...' -ForegroundColor Cyan -NoNewline
        $pollResult = Wait-TemplateReady -Owner $Owner -RepoName $repoName
        if ($pollResult.Ready) {
            Write-Host " ready ($($pollResult.ElapsedSeconds)s)" -ForegroundColor Green
        }
        else {
            Write-Host " timed out after $($pollResult.ElapsedSeconds)s" -ForegroundColor Yellow
            Write-Warning 'Template initialization not confirmed — clone may race.'
        }

        # Create repo secrets needed for agent auth
        #New-RepoSecret 'CLAUDE_CODE_OAUTH_TOKEN'
        Write-Host 'Setting repo secrets and variables...' -ForegroundColor Cyan -NoNewline
        New-RepoSecret -Owner $Owner -RepoName $repoName -SecretName 'GEMINI_API_KEY'
        # New-RepoSecret -Owner $Owner -RepoName $repoName -SecretName 'ZHIPU_API_KEY'
        # need to add repository variables
        #VERSION_PREFIX = '0.0.1'
        New-RepoVariable -Owner $Owner -RepoName $repoName -VariableName 'VERSION_PREFIX' -VariableValue '0.0.1'
        Write-Host ' done' -ForegroundColor Green

        Write-Host "Cloning '$Owner/$repoName'..." -ForegroundColor Cyan -NoNewline
        $clonePath = Get-ClonePath -Parent $CloneParentDir -Name $repoName
        Invoke-GitClone -Owner $Owner -Name $repoName -Dest $clonePath
        Write-Host " done" -ForegroundColor Green
        if (Get-Command Write-RunLog -ErrorAction SilentlyContinue) { Write-RunLog -Level 'INFO' -Step 'clone' -Message "Cloned $Owner/$repoName" -Data @{ clonePath = $clonePath } }

        # Copy plan docs
        Write-Host 'Copying plan docs...' -ForegroundColor Cyan -NoNewline
        Copy-PlanDocs -SourceDir $PlanDocsDir -RepoRoot $clonePath
        Write-Host ' done' -ForegroundColor Green
        if (Get-Command Write-RunLog -ErrorAction SilentlyContinue) { Write-RunLog -Level 'INFO' -Step 'copy-docs' -Message 'Copied plan docs' -Data @{ sourceDir = $PlanDocsDir; repoRoot = $clonePath } }

        # Snapshot file list before replacement
        $preFiles = @(Get-ChildItem -LiteralPath $clonePath -Recurse -Force -File | Where-Object { $_.FullName -notmatch '[/\\]\.git([/\\]|$)' })
        Write-Verbose "[TRACE:Main] Pre-replacement file count: $($preFiles.Count)"
        Write-Verbose "[TRACE:Main] Clone path: $clonePath"
        Write-Verbose "[TRACE:Main] Clone path exists: $(Test-Path -LiteralPath $clonePath)"
        Write-Verbose "[TRACE:Main] TEMPLATE_REPO_NAME: '$TemplateRepoName'"
        Write-Verbose "[TRACE:Main] repoName: '$repoName'"
        Write-Verbose "[TRACE:Main] TEMPLATE_OWNER: '$TemplateOwner' | Owner: '$Owner'"

        # Replace template placeholders in file contents and path names
        Write-Host 'Replacing template placeholders (repo name)...' -ForegroundColor Cyan -NoNewline
        Write-Verbose '[TRACE:Main] --- Step 1: Replace repo name ---'
        Update-TemplatePlaceholders -RepoRoot $clonePath -TemplateText $TemplateRepoName -ReplacementText $repoName
        Assert-NoTemplatePlaceholdersRemaining -RepoRoot $clonePath -TemplateText $TemplateRepoName
        Write-Host ' done' -ForegroundColor Green

        # Replace template owner in image/registry references (e.g. ghcr.io/intel-agency/... -> ghcr.io/nam20485/...)
        $ownerLower = $Owner.ToLower()
        if ($ownerLower -ne $TemplateOwnerLower) {
            Write-Host 'Replacing template placeholders (owner)...' -ForegroundColor Cyan -NoNewline
            Write-Verbose '[TRACE:Main] --- Step 2: Replace owner ---'
            Write-Verbose "Replacing template owner '$TemplateOwner' -> '$Owner' in file contents"
            Update-TemplatePlaceholders -RepoRoot $clonePath -TemplateText $TemplateOwner -ReplacementText $Owner
            Assert-NoTemplatePlaceholdersRemaining -RepoRoot $clonePath -TemplateText $TemplateOwner
            Write-Host ' done' -ForegroundColor Green
        }
        else {
            Write-Verbose "[TRACE:Main] --- Step 2: SKIPPED (owner unchanged: '$Owner' == '$TemplateOwnerLower') ---"
        }

        # Rewrite AGENTS.md to identify this as a project instance, not the source template.
        # Generic placeholder replacements have already run, so the parenthetical now shows the new
        # repo name — we only need to flip the label text and restore the template source reference.
        Write-Host 'Rewriting AGENTS.md instance identification...' -ForegroundColor Cyan -NoNewline
        $agentsMdPath = Join-Path $clonePath 'AGENTS.md'
        if (Test-Path -LiteralPath $agentsMdPath) {
            $agentsMd = Get-Content -LiteralPath $agentsMdPath -Raw
            $oldLabel = '**GitHub template repo**'
            $newLabel = "**project instance** cloned from the ``$TemplateOwner/$TemplateRepoName`` GitHub template"
            if ($agentsMd.Contains($oldLabel)) {
                $agentsMd = $agentsMd.Replace($oldLabel, $newLabel)
                if (-not $DryRun) {
                    Set-Content -LiteralPath $agentsMdPath -Value $agentsMd -NoNewline
                } else {
                    Write-Warning '[dry-run] Would rewrite AGENTS.md instance identification'
                }
                Write-Host ' done' -ForegroundColor Green
            } else {
                Write-Host ' skipped (already updated)' -ForegroundColor DarkGray
            }
        } else {
            Write-Warning "AGENTS.md not found at '$agentsMdPath'"
            Write-Host ' skipped' -ForegroundColor Yellow
        }

        $workspacePath = Join-Path $clonePath "$repoName.code-workspace"
        if (Test-Path -LiteralPath $workspacePath -PathType Leaf) {
            $lastEditorTarget = $workspacePath
        }
        else {
            Write-Verbose "Expected workspace file not found, opening repo folder instead: $workspacePath"
            $lastEditorTarget = $clonePath
        }

        # Commit and push
        Write-Host 'Committing and pushing...' -ForegroundColor Cyan -NoNewline
        $seedCommitMessage = "Seed $repoName from template with plan docs and placeholder replacements"
        $rebased = Invoke-GitCommitAndPush -RepoRoot $clonePath -CommitMessage $seedCommitMessage

        if ($rebased) {
            Write-Host ' rebase required' -ForegroundColor Yellow
            # Template race: rebase pulled in un-replaced template files.
            # Re-run all replacements on the rebased tree.
            Write-Warning 'Template race detected — re-running placeholder replacements after rebase...'

            Write-Host 'Re-replacing template placeholders (repo name) after rebase...' -ForegroundColor Cyan -NoNewline
            Write-Verbose '[TRACE:Main] --- Post-rebase Step 1: Re-replace repo name ---'
            Update-TemplatePlaceholders -RepoRoot $clonePath -TemplateText $TemplateRepoName -ReplacementText $repoName
            Assert-NoTemplatePlaceholdersRemaining -RepoRoot $clonePath -TemplateText $TemplateRepoName
            Write-Host ' done' -ForegroundColor Green

            $ownerLower = $Owner.ToLower()
            if ($ownerLower -ne $TemplateOwnerLower) {
                Write-Host 'Re-replacing template placeholders (owner) after rebase...' -ForegroundColor Cyan -NoNewline
                Write-Verbose '[TRACE:Main] --- Post-rebase Step 2: Re-replace owner ---'
                Update-TemplatePlaceholders -RepoRoot $clonePath -TemplateText $TemplateOwner -ReplacementText $Owner
                Assert-NoTemplatePlaceholdersRemaining -RepoRoot $clonePath -TemplateText $TemplateOwner
                Write-Host ' done' -ForegroundColor Green
            }

            # Re-apply AGENTS.md instance identification rewrite after rebase
            Write-Host 'Re-rewriting AGENTS.md instance identification after rebase...' -ForegroundColor Cyan -NoNewline
            $agentsMdPath = Join-Path $clonePath 'AGENTS.md'
            if (Test-Path -LiteralPath $agentsMdPath) {
                $agentsMd = Get-Content -LiteralPath $agentsMdPath -Raw
                $oldLabel = '**GitHub template repo**'
                $newLabel = "**project instance** cloned from the ``$TemplateOwner/$TemplateRepoName`` GitHub template"
                if ($agentsMd.Contains($oldLabel)) {
                    $agentsMd = $agentsMd.Replace($oldLabel, $newLabel)
                    if (-not $DryRun) {
                        Set-Content -LiteralPath $agentsMdPath -Value $agentsMd -NoNewline
                    } else {
                        Write-Warning '[dry-run] Would rewrite AGENTS.md instance identification (post-rebase)'
                    }
                    Write-Host ' done' -ForegroundColor Green
                } else {
                    Write-Host ' skipped (already updated)' -ForegroundColor DarkGray
                }
            } else {
                Write-Warning "AGENTS.md not found at '$agentsMdPath'"
                Write-Host ' skipped' -ForegroundColor Yellow
            }

            # Amend the seed commit with the post-rebase replacements and force push
            Write-Host 'Amending commit and force-pushing...' -ForegroundColor Cyan -NoNewline
            Invoke-External -FilePath 'git' -ArgumentList @('-C', $clonePath, 'add', '.') | Out-Null
            $amendCommit = Invoke-External -FilePath 'git' -ArgumentList @('-C', $clonePath, 'commit', '--amend', '--no-edit') -AllowFail
            if ($amendCommit.ExitCode -ne 0) {
                $amendMsg = ($amendCommit.Output -join ' ')
                if ($amendMsg -notmatch 'nothing to commit') { throw "git commit --amend failed: $amendMsg" }
            }
            Invoke-External -FilePath 'git' -ArgumentList @('-C', $clonePath, 'push', '--force-with-lease', 'origin', 'main') | Out-Null
            Write-Host ' done' -ForegroundColor Green
        }
        else {
            Write-Host ' done' -ForegroundColor Green
        }

        # Output clone destination path
        $repoUrl = "https://github.com/$Owner/$repoName"
        Write-Output $clonePath
        Write-Host "SUCCESS: '$clonePath' created and checked in ($repoUrl) " -ForegroundColor Green        
        
        Write-Host -ForegroundColor Green       
        if (Get-Command Write-RunLog -ErrorAction SilentlyContinue) { Write-RunLog -Level 'INFO' -Step 'repo-done' -Message "Repo complete: $repoName" -Data @{ clonePath = $clonePath } }

        # Trigger project-setup workflow on the new repo (legacy path, preserved
        # for backward compatibility with other templates that still rely on the
        # /orchestrate-dynamic-workflow project-setup dispatch).
        if ($TriggerProjectSetup -and -not $SkipProjectSetup) {
            Write-Host 'Triggering project-setup workflow...' -ForegroundColor Cyan -NoNewline
            $triggerScript = Join-Path $PSScriptRoot 'trigger-project-setup.ps1'
            if (Test-Path -LiteralPath $triggerScript) {
                $bootstrapLabelsFile = Join-Path $clonePath '.github/.labels.json'
                $triggerParams = @{ Repo = "$Owner/$repoName" }
                if (Test-Path -LiteralPath $bootstrapLabelsFile) {
                    $triggerParams['BootstrapLabelsFile'] = $bootstrapLabelsFile
                }
                elseif (-not $DryRun) {
                    throw "Expected bootstrap labels file not found: $bootstrapLabelsFile"
                }
                if ($DryRun) { $triggerParams['DryRun'] = $true }
                & $triggerScript @triggerParams
                #Write-Host ' done' -ForegroundColor Green
            } else {
                Write-Warning "trigger-project-setup.ps1 not found at '$triggerScript'; skipping workflow trigger"
            }
        } else {
            if ($SkipProjectSetup) {
                Write-Verbose 'Skipping legacy project-setup trigger (-SkipProjectSetup); caller will invoke trigger-gh-issue-tracking-init.ps1 separately.'
            } else {
                Write-Verbose 'Skipping project-setup workflow trigger (-TriggerProjectSetup:$false)'
            }
        }
    }

    if (-not $Yes) {
        $launch = Read-Host 'Launch editor? (y/N)'
        if ( ($launch ?? '').Trim().ToLower() -eq 'y' -or $LaunchEditor ) {
            code-insiders --profile $EditorProfile $lastEditorTarget
        }
    }
    else {
        if ($LaunchEditor -and $lastEditorTarget) { code-insiders --profile $EditorProfile $lastEditorTarget }
    }

    Write-Host '=== All done ===' -ForegroundColor Green
    if (Get-Command Complete-RunLog -ErrorAction SilentlyContinue) { Complete-RunLog -Status 'SUCCESS' }
}
catch {
    if (Get-Command Complete-RunLog -ErrorAction SilentlyContinue) { Complete-RunLog -Status 'FAILURE' -ErrorMessage $_.Exception.Message }
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
