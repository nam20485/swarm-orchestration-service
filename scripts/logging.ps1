#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
JSONL structured run-logging module for forensic debugging.

.DESCRIPTION
Provides Start-RunLog, Write-RunLog, and Complete-RunLog functions that write
timestamped JSONL entries to a per-run log file under logs/.
Each entry contains a timestamp, level, step name, message, and optional data bag.
#>

Set-StrictMode -Version Latest

# Module-scoped state
$script:RunLogPath = $null
$script:RunLogStartTime = $null
$script:RunLogId = $null

function Start-RunLog {
    [CmdletBinding()]
    param(
        [Parameter()][string]$LogDir = (Join-Path $PSScriptRoot '..' 'logs'),
        [Parameter()][string]$RunName = 'create-repo'
    )
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    $script:RunLogId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([System.IO.Path]::GetRandomFileName().Split('.')[0])
    $script:RunLogPath = Join-Path $LogDir "$RunName-$($script:RunLogId).jsonl"
    $script:RunLogStartTime = [DateTimeOffset]::UtcNow

    Write-RunLog -Level 'INFO' -Step 'init' -Message "Run started: $RunName" -Data @{
        runId    = $script:RunLogId
        runName  = $RunName
        pid      = $PID
        host     = [System.Environment]::MachineName
        user     = [System.Environment]::UserName
        psVersion = $PSVersionTable.PSVersion.ToString()
    }
    return $script:RunLogPath
}

function Write-RunLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('DEBUG','INFO','WARN','ERROR')][string]$Level,
        [Parameter(Mandatory)][string]$Step,
        [Parameter(Mandatory)][string]$Message,
        [Parameter()][hashtable]$Data = @{}
    )
    if (-not $script:RunLogPath) { return }
    $entry = [ordered]@{
        ts      = [DateTimeOffset]::UtcNow.ToString('o')
        runId   = $script:RunLogId
        level   = $Level
        step    = $Step
        message = $Message
    }
    if ($Data.Count -gt 0) { $entry['data'] = $Data }
    $json = $entry | ConvertTo-Json -Compress -Depth 5
    [System.IO.File]::AppendAllText($script:RunLogPath, "$json`n")
}

function Complete-RunLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('SUCCESS','FAILURE')][string]$Status,
        [Parameter()][string]$ErrorMessage = ''
    )
    if (-not $script:RunLogPath) { return }
    $elapsed = ([DateTimeOffset]::UtcNow - $script:RunLogStartTime).TotalSeconds
    $data = @{ elapsedSeconds = [math]::Round($elapsed, 2) }
    if ($ErrorMessage) { $data['error'] = $ErrorMessage }
    Write-RunLog -Level $(if ($Status -eq 'SUCCESS') { 'INFO' } else { 'ERROR' }) `
                 -Step 'complete' -Message "Run finished: $Status" -Data $data
    $script:RunLogPath = $null
    $script:RunLogStartTime = $null
    $script:RunLogId = $null
}
