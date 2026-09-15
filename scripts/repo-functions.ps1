#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
Shared helper functions for repository creation scripts.
Extracted from create-repo-with-plan-docs.ps1 so tests can dot-source
this file directly while Pester tracks line-level code coverage.
#>

function Test-ToolExists
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue))
    {
        throw "Required tool not found on PATH: $Name"
    }
}

function Get-RandomSuffix
{
    [CmdletBinding()]
    param()
    $words = @('alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot', 'golf', 'hotel', 'india', 'juliet', 'kilo', 'lima', 'mike', 'november', 'oscar', 'papa', 'quebec', 'romeo', 'sierra', 'tango', 'uniform', 'victor', 'whiskey', 'xray', 'yankee', 'zulu')
    $word = Get-Random -InputObject $words
    $num = Get-Random -Minimum 10 -Maximum 100 # two digits 10-99
    return "$word$($num)"
}

function Get-LetterSuffix
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][int]$Index)
    if ($Index -lt 1) { throw 'Index must be a positive integer.' }
    $letters = ''
    $remaining = $Index
    $alphabetStart = [int][char]'a'
    while ($remaining -gt 0)
    {
        $remaining--
        $charCode = $alphabetStart + ($remaining % 26)
        $letters = [char][int]$charCode + $letters
        $remaining = [int][math]::Floor($remaining / 26)
    }
    return $letters
}

function Get-RepoNamesForSuffix
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RepoName,
        [Parameter(Mandatory)][string]$Suffix,
        [Parameter(Mandatory)][int]$Count
    )
    if ($Count -eq 1)
    {
        return @("$RepoName-$Suffix")
    }
    $names = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $Count; $i++)
    {
        $letterSuffix = Get-LetterSuffix -Index $i
        $names.Add("$RepoName-$Suffix-$letterSuffix")
    }
    return $names.ToArray()
}

function Invoke-External
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter()][string[]]$ArgumentList = @(),
        [switch]$AllowFail
    )
    $cmd = "$FilePath $($ArgumentList -join ' ')"
    Write-Verbose ">> $cmd"
    if ($DryRun) { return @{ ExitCode = 0; Output = @('<dry-run>') } }
    $out = & $FilePath @ArgumentList 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFail)
    {
        # Include arguments to make failures easier to diagnose
        $full = "$FilePath $($ArgumentList -join ' ')"
        throw ("Command failed ({0}): {1}`n{2}" -f $code, $full, ($out -join "`n"))
    }
    return @{ ExitCode = $code; Output = $out }
}

function Test-RepoExists
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Owner, [Parameter(Mandatory)][string]$Name)
    if ($DryRun) { return $false }
    $res = Invoke-External -FilePath 'gh' -ArgumentList @('repo', 'view', "$Owner/$Name") -AllowFail
    return ($res.ExitCode -eq 0)
}

function New-RepoSecret
{
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$RepoName,
        [Parameter(Mandatory)][string]$SecretName
    )
    $secretBody = [System.Environment]::GetEnvironmentVariable($SecretName)
    if (-not $secretBody) { throw "Environment variable for secret '$SecretName' not found." }
    $ghArgs = @('secret', 'set', $SecretName, '--body', $secretBody, '--repo', "$Owner/$RepoName")
    Write-Verbose "Creating GitHub repo secret: $SecretName for $Owner/$RepoName"
    if ($PSCmdlet.ShouldProcess($SecretName, 'Create GitHub repo secret'))
    {
        Invoke-External -FilePath 'gh' -ArgumentList $ghArgs | Out-Null
    }
    else
    {
        Write-Verbose 'Creation skipped by ShouldProcess'
    }
}

function New-RepoVariable
{
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$RepoName,
        [Parameter(Mandatory)][string]$VariableName,
        [Parameter(Mandatory)][string]$VariableValue
    )	
    $ghArgs = @('variable', 'set', $VariableName, '--body', $VariableValue, '--repo', "$Owner/$RepoName")
    Write-Verbose "Creating GitHub repo variable: $VariableName for $Owner/$RepoName"
    if ($PSCmdlet.ShouldProcess($VariableName, 'Create GitHub repo variable'))
    {
        Invoke-External -FilePath 'gh' -ArgumentList $ghArgs | Out-Null
    }
    else
    {
        Write-Verbose 'Creation skipped by ShouldProcess'
    }
}

function Get-TemplatePlaceholderMatches
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$TemplateText
    )

    $templatePattern = [regex]::Escape($TemplateText)
    Write-Verbose "[TRACE:Scan] Scanning for placeholder matches under: $RepoRoot"
    Write-Verbose "[TRACE:Scan] Template text: '$TemplateText' | Regex pattern: '$templatePattern'"
    $placeholderMatches = New-Object System.Collections.Generic.List[object]

    $allItems = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force | Where-Object {
        $_.FullName -notmatch '[/\\]\.git([/\\]|$)' -and $_.Name -match $templatePattern
    })
    Write-Verbose "[TRACE:Scan] Found $($allItems.Count) path(s) matching template pattern in name"
    foreach ($path in $allItems)
    {
        Write-Verbose "[TRACE:Scan]   Path match: $($path.FullName)"
        $placeholderMatches.Add([PSCustomObject]@{
            MatchType = 'Path'
            Path = $path.FullName
        })
    }

    $allFiles = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -File | Where-Object {
        $_.FullName -notmatch '[/\\]\.git([/\\]|$)'
    })
    Write-Verbose "[TRACE:Scan] Scanning $($allFiles.Count) file(s) for content matches"
    foreach ($file in $allFiles)
    {
        try
        {
            $content = [System.IO.File]::ReadAllText($file.FullName)
        }
        catch
        {
            Write-Verbose "[TRACE:Scan] Skipping unreadable file: $($file.FullName) — $($_.Exception.Message)"
            continue
        }

        if ($content -match $templatePattern)
        {
            Write-Verbose "[TRACE:Scan]   Content match: $($file.FullName)"
            $placeholderMatches.Add([PSCustomObject]@{
                MatchType = 'Content'
                Path = $file.FullName
            })
        }
    }

    Write-Verbose "[TRACE:Scan] Total matches found: $($placeholderMatches.Count)"
    return $placeholderMatches.ToArray()
}

function Update-TemplatePlaceholders
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$TemplateText,
        [Parameter(Mandatory)][string]$ReplacementText
    )

    $templatePattern = [regex]::Escape($TemplateText)
    Write-Verbose "[TRACE:Replace] === Update-TemplatePlaceholders ==="
    Write-Verbose "[TRACE:Replace] RepoRoot: $RepoRoot"
    Write-Verbose "[TRACE:Replace] TemplateText: '$TemplateText' | ReplacementText: '$ReplacementText'"
    Write-Verbose "[TRACE:Replace] Regex pattern: '$templatePattern'"
    Write-Verbose "[TRACE:Replace] RepoRoot exists: $(Test-Path -LiteralPath $RepoRoot)"
    Write-Verbose "[TRACE:Replace] RepoRoot resolved: $(Resolve-Path -LiteralPath $RepoRoot -ErrorAction SilentlyContinue)"

    $templatePaths = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force | Where-Object {
        $_.FullName -notmatch '[/\\]\.git([/\\]|$)' -and $_.Name -match $templatePattern
    })
    Write-Verbose "[TRACE:Replace] Path matches (name contains template text): $($templatePaths.Count)"

    $allFiles = @(Get-ChildItem -LiteralPath $RepoRoot -Recurse -Force -File | Where-Object {
        $_.FullName -notmatch '[/\\]\.git([/\\]|$)'
    })
    Write-Verbose "[TRACE:Replace] Total files to scan for content: $($allFiles.Count)"

    $replacedCount = 0
    $skippedCount = 0
    $noMatchCount = 0
    foreach ($file in $allFiles)
    {
        try
        {
            $content = [System.IO.File]::ReadAllText($file.FullName)
        }
        catch
        {
            Write-Verbose "[TRACE:Replace] SKIP (unreadable): $($file.FullName) — $($_.Exception.Message)"
            $skippedCount++
            continue
        }

        if ($content -notmatch $templatePattern)
        {
            $noMatchCount++
            continue
        }

        $newContent = $content -replace $templatePattern, $ReplacementText
        $replacedCount++
        Write-Verbose "[TRACE:Replace] MATCH [$replacedCount]: $($file.FullName) (size: $($content.Length) bytes)"
        if ($DryRun)
        {
            Write-Verbose "[TRACE:Replace]   [dry-run] Would replace template text"
        }
        else
        {
            [System.IO.File]::WriteAllText($file.FullName, $newContent)
            # Verify the write persisted
            $verifyContent = [System.IO.File]::ReadAllText($file.FullName)
            if ($verifyContent -match $templatePattern)
            {
                Write-Verbose "[TRACE:Replace]   WARNING: File still contains template text after write! $($file.FullName)"
            }
            else
            {
                Write-Verbose "[TRACE:Replace]   Verified: template text removed after write"
            }
        }
    }

    Write-Verbose "[TRACE:Replace] Content replacement summary: $replacedCount replaced, $noMatchCount no-match, $skippedCount skipped (of $($allFiles.Count) total)"

    Write-Verbose "[TRACE:Replace] Renaming $($templatePaths.Count) path(s) matching template pattern"
    foreach ($path in ($templatePaths | Sort-Object { $_.FullName.Length } -Descending))
    {
        $newName = $path.Name -replace $templatePattern, $ReplacementText
        $newPath = Join-Path $path.DirectoryName $newName
        Write-Verbose "[TRACE:Replace] RENAME: $($path.FullName) -> $newPath"
        if ($DryRun)
        {
            Write-Verbose "[TRACE:Replace]   [dry-run] Would rename"
        }
        else
        {
            Rename-Item -LiteralPath $path.FullName -NewName $newName | Out-Null
        }
    }

    Write-Verbose "[TRACE:Replace] === Update-TemplatePlaceholders complete ==="
}

function Assert-NoTemplatePlaceholdersRemaining
{
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$TemplateText
    )

    Write-Verbose "[TRACE:Assert] Checking for remaining placeholders: '$TemplateText' under $RepoRoot"
    $remainingMatches = @(Get-TemplatePlaceholderMatches -RepoRoot $RepoRoot -TemplateText $TemplateText)
    Write-Verbose "[TRACE:Assert] Remaining matches: $($remainingMatches.Count)"
    if ($remainingMatches.Count -eq 0)
    {
        Write-Verbose "[TRACE:Assert] PASS: No remaining template placeholders"
        return
    }

    $matchSummary = $remainingMatches |
        Select-Object -First 20 |
        ForEach-Object { "- [$($_.MatchType)] $($_.Path)" }

    Write-Verbose "[TRACE:Assert] FAIL: $($remainingMatches.Count) remaining match(es)"
    throw "Template placeholder replacement incomplete. Remaining matches:`n$($matchSummary -join "`n")"
}

function New-GitHubRepository
{
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('public', 'private')][string]$Visibility,
        [Parameter(Mandatory)][string]$Template
    )
    $ghArgs = @('repo', 'create', "$Owner/$Name")
    if ($Visibility -eq 'private') { $ghArgs += '--private' } else { $ghArgs += '--public' }
    # Create from template repo explicitly
    $ghArgs += @('--template', $Template)
    Write-Verbose "Creating GitHub repository: $Owner/$Name"
    if ($PSCmdlet.ShouldProcess("$Owner/$Name", 'Create GitHub repository'))
    {
        Invoke-External -FilePath 'gh' -ArgumentList $ghArgs | Out-Null
    }
 else
    {
        Write-Verbose 'Creation skipped by ShouldProcess'
    }
}

function Get-ClonePath
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Parent, [Parameter(Mandatory)][string]$Name)
    if (-not (Test-Path -LiteralPath $Parent))
    {
        New-Item -ItemType Directory -Path $Parent | Out-Null
    }
    $parentResolved = (Resolve-Path -LiteralPath $Parent).Path
    $dest = Join-Path $parentResolved $Name
    return $dest
}

function Invoke-GitClone
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Owner, [Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Dest)
    if (Test-Path -LiteralPath $Dest)
    {
        # Validate the existing clone has a .git directory and a valid HEAD
        $gitDir = Join-Path $Dest '.git'
        if (-not (Test-Path -LiteralPath $gitDir -PathType Container))
        {
            throw "Clone destination exists but is not a git repo (no .git/): $Dest"
        }
        $headCheck = Invoke-External -FilePath 'git' -ArgumentList @('-C', $Dest, 'rev-parse', '--verify', 'HEAD') -AllowFail
        if ($headCheck.ExitCode -ne 0)
        {
            throw "Clone destination exists but has no valid HEAD: $Dest"
        }
        Write-Verbose "Clone destination exists and is valid: $Dest (skipping clone)"
        return
    }
    New-Item -ItemType Directory -Path $Dest | Out-Null
    Invoke-External -FilePath 'git' -ArgumentList @('clone', "git@github.com:$Owner/$Name.git", $Dest) | Out-Null
}

function Copy-PlanDocs
{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$SourceDir, [Parameter(Mandatory)][string]$RepoRoot)
    $docs = Join-Path $RepoRoot $docsDir
    if ($DryRun)
    {
        Write-Verbose "[dry-run] Would copy plan docs: $SourceDir -> $docs"
        return
    }
    if (-not (Test-Path -LiteralPath $SourceDir)) { throw "Plan docs directory not found: $SourceDir" }
    if (-not (Test-Path -LiteralPath $docs)) { New-Item -ItemType Directory -Path $docs | Out-Null }
    $srcResolved = (Resolve-Path -LiteralPath $SourceDir).Path
    Write-Verbose "Copying plan docs: $srcResolved -> $docs"
    Copy-Item "$srcResolved/*" -Destination $docs -Recurse -Force
}

function Invoke-GitCommitAndPush
{
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Low')]
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$CommitMessage
    )
    # Ensure we're on a valid branch (handle unborn HEAD in freshly created repos)
    $hasHead = Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'rev-parse', '--verify', 'HEAD') -AllowFail
    if ($hasHead.ExitCode -ne 0)
    {
        # No commits yet; create/switch to main branch explicitly
        $sw = Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'switch', '-c', 'main') -AllowFail
        if ($sw.ExitCode -ne 0)
        {
            # Fallback for older Git
            Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'checkout', '-b', 'main') | Out-Null
        }
    }

    Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'add', '.') | Out-Null
    $commit = Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'commit', '-m', $CommitMessage) -AllowFail
    if ($commit.ExitCode -ne 0)
    {
        $msg = ($commit.Output -join ' ')
        if ($msg -match 'nothing to commit')
        {
            Write-Warning "Nothing to commit — expected replacement changes but working tree is clean. Possible template race."
        }
        else
        {
            throw "git commit failed: $msg"
        }
    }
    # Determine current branch and push explicitly (handles fresh repos)
    $branch = (Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'branch', '--show-current')).Output | Select-Object -First 1
    $branch = $branch.Trim()
    if (-not $branch) { $branch = 'main' }
    $rebased = $false
    if ($PSCmdlet.ShouldProcess($RepoRoot, "Push changes to origin/$branch"))
    {
        # Use -u to set upstream on first push
        $push = Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'push', '-u', 'origin', $branch) -AllowFail
        if ($push.ExitCode -ne 0)
        {
            # Handle non-fast-forward race when GitHub finishes templating after our clone
            $pushMsg = ($push.Output -join ' ')
            if ($pushMsg -match 'fetch first' -or $pushMsg -match 'non-fast-forward' -or $pushMsg -match 'failed to push some refs')
            {
                Write-Warning "Push rejected (template race detected). Rebasing onto origin/$branch and retrying..."
                # Pull with rebase to integrate remote commits without a merge commit
                Invoke-External -FilePath 'git' -ArgumentList @('-C', $RepoRoot, 'pull', '--rebase', 'origin', $branch) | Out-Null
                $rebased = $true
            }
            else
            {
                throw ('git push failed: {0}' -f $pushMsg)
            }
        }
    }
    # Return whether a rebase occurred so callers can re-run replacements
    return $rebased
}

function Wait-TemplateReady {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Owner,
        [Parameter(Mandatory)][string]$RepoName,
        [int]$TimeoutSeconds = 60,
        [int]$PollIntervalSeconds = 3
    )
    if ($DryRun) { return @{ Ready = $true; ElapsedSeconds = 0 } }
    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        $commitCount = Invoke-External -FilePath 'gh' -ArgumentList @('api', "repos/$Owner/$RepoName/commits?per_page=1", '--jq', 'length') -AllowFail
        $countVal = ($commitCount.Output | Select-Object -First 1) -as [int]
        if ($commitCount.ExitCode -eq 0 -and $countVal -gt 0) {
            return @{ Ready = $true; ElapsedSeconds = $elapsed }
        }
        Start-Sleep -Seconds $PollIntervalSeconds
        $elapsed += $PollIntervalSeconds
        Write-Host "." -NoNewline
    }
    return @{ Ready = $false; ElapsedSeconds = $elapsed }
}
