#!/usr/bin/env pwsh
<#
.SYNOPSIS
    End-to-end orchestration smoke in the simulator: boots the real webhook
    listener and drives signed GitHub deliveries through every endpoint
    behavior, asserting HTTP statuses and the EventStore outcomes via the
    GET /events SSE surface.

.DESCRIPTION
    CI-safe and hermetic: NO docker, NO opencode, NO network beyond the
    loopback interface. The listener boots with ACP_ENABLED=false (the
    queue consumer then marks envelopes consumed without driving an agent
    session — the Phase 1 placeholder path) and SANDBOX_ENABLED=false.

    Scenarios (one signed webhook each, against the real uvicorn process):

      1. happy accept      issues.labeled with a workflow label -> 202
                           accepted; events webhook_received,
                           webhook_accepted, prompt_queued (exactly one),
                           prompt_consumed {ok: true}
      2. ping              ping event -> 200 pong (no events)
      3. bad signature     tampered X-Hub-Signature-256 -> 401 (no events)
      4. filtered label    non-workflow label -> 202 ignored;
                           webhook_filtered with reason, no
                           webhook_accepted
      5. duplicate         redelivery of scenario 1 -> 202 accepted;
                           webhook_duplicate emitted, still exactly one
                           prompt_queued (delivery-id dedup)

    Event assertions read GET /events (SSE): each connection replays the
    store's ring buffer, so a read stops as soon as the expected event
    types have been seen (bounded by -EventTimeoutSeconds).

    Exit codes: 0 = all scenarios passed; 1 = any failure (assertion,
    timeout, or the listener failed to start/boot).

    Requires the repo python venv (.venv) with the service requirements —
    bootstrapped automatically when missing (mirrors validation.ps1's
    python branch).

.PARAMETER Port
    Loopback port the listener binds (default 8765).

.PARAMETER WebhookSecret
    HMAC secret for the run; a known placeholder value, never a real
    credential.

.PARAMETER EventTimeoutSeconds
    Budget for each GET /events read to observe its expected events.

.EXAMPLE
    pwsh scripts/e2e-orchestration.ps1
#>
param(
    [int]$Port = 8765,
    [string]$WebhookSecret = 'FAKE-WEBHOOK-SECRET-FOR-TESTING',
    [int]$EventTimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serviceDir = Join-Path $repoRoot 'src' 'webhook_receiver'
$venvDir = Join-Path $repoRoot '.venv'
$venvPython = if ($IsWindows) { Join-Path $venvDir 'Scripts' 'python.exe' } else { Join-Path $venvDir 'bin' 'python' }
$runTag = [guid]::NewGuid().ToString('N').Substring(0, 8)
$logDir = Join-Path ([System.IO.Path]::GetTempPath()) "e2e-orchestration-$runTag"
$script:Listener = $null
$script:EnvBackup = $null

function Assert-Equal {
    param([string]$Name, $Actual, $Expected)
    if ("$Actual" -ne "$Expected") {
        throw "ASSERTION FAILED [$Name]: expected '$Expected' but got '$Actual'"
    }
    Write-Host "PASS: $Name"
}

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail = '')
    if (-not $Condition) {
        $suffix = if ($Detail) { ": $Detail" } else { '' }
        throw "ASSERTION FAILED [$Name]$suffix"
    }
    Write-Host "PASS: $Name"
}

function Get-Signature {
    param([string]$Body, [string]$Secret)
    $hmac = [System.Security.Cryptography.HMACSHA256]::new(
        [System.Text.Encoding]::UTF8.GetBytes($Secret))
    try {
        $hash = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Body))
        return 'sha256=' + (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
    }
    finally {
        $hmac.Dispose()
    }
}

function New-LabelPayload {
    param([string]$Repo, [string]$Label, [string]$Sender)
    return ([pscustomobject]@{
        action     = 'labeled'
        sender     = [pscustomobject]@{ login = $Sender }
        label      = [pscustomobject]@{ name = $Label }
        issue      = [pscustomobject]@{
            number = 1
            labels = @([pscustomobject]@{ name = $Label })
        }
        repository = [pscustomobject]@{ full_name = $Repo }
    } | ConvertTo-Json -Depth 10 -Compress)
}

function Invoke-GithubWebhook {
    param([string]$Event, [string]$DeliveryId, [string]$Body, [string]$Signature)
    return Invoke-WebRequest `
        -Uri "http://127.0.0.1:$Port/webhooks/github" `
        -Method Post -Body $Body -ContentType 'application/json' `
        -Headers @{
            'X-GitHub-Event'      = $Event
            'X-GitHub-Delivery'   = $DeliveryId
            'X-Hub-Signature-256' = $Signature
        } `
        -SkipHttpErrorCheck -UseBasicParsing -TimeoutSec 10
}

function Get-DashboardEvents {
    # Read GET /events until every name in $WaitFor has been seen (the store
    # replays its ring buffer on subscribe) or the timeout budget expires.
    param([string[]]$WaitFor)
    $remaining = [System.Collections.Generic.HashSet[string]]::new([string[]]$WaitFor)
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds($EventTimeoutSeconds + 5)
    try {
        $response = $client.GetAsync(
            "http://127.0.0.1:$Port/events",
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            throw "GET /events returned HTTP $([int]$response.StatusCode)"
        }
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $reader = [System.IO.StreamReader]::new($stream)
        $events = [System.Collections.Generic.List[object]]::new()
        $current = @{}
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        while ($remaining.Count -gt 0) {
            if ($watch.Elapsed.TotalSeconds -gt $EventTimeoutSeconds) {
                throw ("timed out after ${EventTimeoutSeconds}s waiting for events: " +
                    (@($remaining) -join ', '))
            }
            $line = $reader.ReadLine()
            if ($null -eq $line) {
                throw ('SSE stream closed before receiving: ' +
                    (@($remaining) -join ', '))
            }
            if ($line -eq '') {
                if ($current.Count -gt 0) {
                    $events.Add([pscustomobject]@{
                        id   = [int]$current['id']
                        type = $current['event']
                        data = $current['data'] | ConvertFrom-Json
                    })
                    [void]$remaining.Remove($current['event'])
                    $current = @{}
                }
                continue
            }
            if ($line.StartsWith(':')) { continue }  # keepalive comment
            $sep = $line.IndexOf(':')
            $field = $line.Substring(0, $sep)
            $value = $line.Substring($sep + 1).TrimStart(' ')
            if (-not $current.ContainsKey($field)) { $current[$field] = $value }
        }
        return $events
    }
    finally {
        $client.Dispose()
    }
}

function Assert-DeliveryEvents {
    param([object[]]$Events, [string]$DeliveryId, [string[]]$ExpectedTypes)
    foreach ($type in $ExpectedTypes) {
        Assert-True -Name "event $type recorded for delivery $DeliveryId" `
            -Condition (@($Events | Where-Object {
                $_.type -eq $type -and $_.data.delivery_id -eq $DeliveryId
            }).Count -gt 0)
    }
}

function New-RunEnvironment {
    # Back up the caller's values for the knobs we set; restored in finally.
    $script:EnvBackup = @{}
    foreach ($name in @(
        'OS_WEBHOOK_SECRET', 'ACP_ENABLED', 'SANDBOX_ENABLED',
        'WEBHOOK_HOST', 'WEBHOOK_PORT', 'WEBHOOK_LOG_LEVEL', 'PYTHONPATH'
    )) {
        $script:EnvBackup[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    $env:OS_WEBHOOK_SECRET = $WebhookSecret
    $env:ACP_ENABLED = 'false'
    $env:SANDBOX_ENABLED = 'false'
    $env:WEBHOOK_HOST = '127.0.0.1'
    $env:WEBHOOK_PORT = "$Port"
    $env:WEBHOOK_LOG_LEVEL = 'info'
    # The service lives under src/ (the compose image bakes the same layout
    # into /app); tests get the same path via conftest.py.
    $srcDir = Join-Path $repoRoot 'src'
    $existing = $script:EnvBackup['PYTHONPATH']
    $env:PYTHONPATH = if ($existing) { "$srcDir$([IO.Path]::PathSeparator)$existing" } else { $srcDir }
}

function Restore-RunEnvironment {
    foreach ($entry in $script:EnvBackup.GetEnumerator()) {
        if ($null -eq $entry.Value) {
            Remove-Item -Path "env:$($entry.Key)" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value)
        }
    }
}

# =============================================================================
# Main
# =============================================================================
try {
    # Venv bootstrap: mirrors validation.ps1's python branch.
    if (-not (Test-Path $venvPython)) {
        Write-Host '.venv not found; bootstrapping with the service requirements...' `
            -ForegroundColor Gray
        $pythonCmd = $null
        foreach ($candidate in @('python3', 'python')) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                $pythonCmd = $candidate; break
            }
        }
        if (-not $pythonCmd) {
            throw 'python3 not found and no .venv exists (install Python 3.12+ first)'
        }
        & $pythonCmd -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw 'python venv creation failed' }
        & $venvPython -m pip install --quiet --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
        & $venvPython -m pip install --quiet -r (Join-Path $serviceDir 'requirements-dev.txt')
        if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    }

    New-RunEnvironment
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir 'listener-stdout.log'
    $stderrLog = Join-Path $logDir 'listener-stderr.log'

    Write-Host "Booting listener on 127.0.0.1:$Port (ACP disabled, sandbox disabled)..."
    $script:Listener = Start-Process -FilePath $venvPython `
        -ArgumentList @('-m', 'webhook_receiver') `
        -WorkingDirectory $repoRoot -PassThru -NoNewWindow `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

    $healthDeadline = [DateTime]::UtcNow.AddSeconds(20)
    while ($true) {
        if ($script:Listener.HasExited) {
            throw "listener exited during startup (code $($script:Listener.ExitCode)); stderr: $((Get-Content $stderrLog -Raw))"
        }
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" `
                -UseBasicParsing -TimeoutSec 2
            if ($health.StatusCode -eq 200) { break }
        }
        catch {
            if ([DateTime]::UtcNow -ge $healthDeadline) { throw }
        }
        Start-Sleep -Milliseconds 250
    }
    Assert-Equal -Name 'GET /health returns ok' `
        -Actual (($health.Content | ConvertFrom-Json).status) -Expected 'ok'

    # -- Scenario 1: happy accept (workflow label) --------------------------
    $body = New-LabelPayload -Repo 'owner/e2e-repo' `
        -Label 'orchestration:plan-approved' -Sender 'nam20485'
    $resp = Invoke-GithubWebhook -Event 'issues' -DeliveryId 'e2e-accept-1' `
        -Body $body -Signature (Get-Signature -Body $body -Secret $WebhookSecret)
    Assert-Equal -Name 'happy accept returns 202' -Actual $resp.StatusCode -Expected 202
    Assert-Equal -Name 'happy accept body status accepted' `
        -Actual (($resp.Content | ConvertFrom-Json).status) -Expected 'accepted'

    $events = Get-DashboardEvents -WaitFor @('prompt_consumed')
    Assert-DeliveryEvents -Events $events -DeliveryId 'e2e-accept-1' -ExpectedTypes @(
        'webhook_received', 'webhook_accepted', 'prompt_queued', 'prompt_consumed'
    )
    $queued = @($events | Where-Object {
        $_.type -eq 'prompt_queued' -and $_.data.delivery_id -eq 'e2e-accept-1'
    })
    Assert-Equal -Name 'exactly one prompt_queued for the delivery' `
        -Actual $queued.Count -Expected 1
    $consumed = @($events | Where-Object {
        $_.type -eq 'prompt_consumed' -and $_.data.delivery_id -eq 'e2e-accept-1'
    })
    Assert-Equal -Name 'prompt_consumed recorded ok' `
        -Actual $consumed[0].data.ok -Expected $true

    # -- Scenario 2: ping ---------------------------------------------------
    $resp = Invoke-GithubWebhook -Event 'ping' -DeliveryId 'e2e-ping-1' `
        -Body '{}' -Signature (Get-Signature -Body '{}' -Secret $WebhookSecret)
    Assert-Equal -Name 'ping returns 200' -Actual $resp.StatusCode -Expected 200
    Assert-Equal -Name 'ping body status pong' `
        -Actual (($resp.Content | ConvertFrom-Json).status) -Expected 'pong'

    # -- Scenario 3: bad signature -------------------------------------------
    $resp = Invoke-GithubWebhook -Event 'issues' -DeliveryId 'e2e-badsig-1' `
        -Body $body -Signature ('sha256=' + ('0' * 64))
    Assert-Equal -Name 'bad signature returns 401' -Actual $resp.StatusCode -Expected 401
    $events = Get-DashboardEvents -WaitFor @('prompt_consumed')
    Assert-True -Name 'bad signature emits no events for the delivery' `
        -Condition (@($events | Where-Object {
            $_.data.delivery_id -eq 'e2e-badsig-1'
        }).Count -eq 0)

    # -- Scenario 4: filtered non-workflow label ------------------------------
    $filtered = New-LabelPayload -Repo 'owner/e2e-repo' -Label 'bug' -Sender 'nam20485'
    $resp = Invoke-GithubWebhook -Event 'issues' -DeliveryId 'e2e-filtered-1' `
        -Body $filtered -Signature (Get-Signature -Body $filtered -Secret $WebhookSecret)
    Assert-Equal -Name 'non-workflow label returns 202' -Actual $resp.StatusCode -Expected 202
    Assert-Equal -Name 'non-workflow label body status ignored' `
        -Actual (($resp.Content | ConvertFrom-Json).status) -Expected 'ignored'
    $events = Get-DashboardEvents -WaitFor @('webhook_filtered')
    $filterEvents = @($events | Where-Object {
        $_.type -eq 'webhook_filtered' -and $_.data.delivery_id -eq 'e2e-filtered-1'
    })
    Assert-True -Name 'webhook_filtered recorded with reason' `
        -Condition ($filterEvents.Count -eq 1) `
        -Detail "count=$($filterEvents.Count)"
    Assert-True -Name 'filter reason names the label' `
        -Condition ($filterEvents[0].data.reason -like "*'bug'*")
    Assert-True -Name 'no webhook_accepted for the filtered delivery' `
        -Condition (@($events | Where-Object {
            $_.type -eq 'webhook_accepted' -and $_.data.delivery_id -eq 'e2e-filtered-1'
        }).Count -eq 0)

    # -- Scenario 5: duplicate delivery (dedup) -------------------------------
    $resp = Invoke-GithubWebhook -Event 'issues' -DeliveryId 'e2e-accept-1' `
        -Body $body -Signature (Get-Signature -Body $body -Secret $WebhookSecret)
    Assert-Equal -Name 'duplicate delivery still acked 202' `
        -Actual $resp.StatusCode -Expected 202
    $events = Get-DashboardEvents -WaitFor @('webhook_duplicate')
    Assert-True -Name 'webhook_duplicate recorded for the redelivery' `
        -Condition (@($events | Where-Object {
            $_.type -eq 'webhook_duplicate' -and $_.data.delivery_id -eq 'e2e-accept-1'
        }).Count -eq 1)
    $queued = @($events | Where-Object {
        $_.type -eq 'prompt_queued' -and $_.data.delivery_id -eq 'e2e-accept-1'
    })
    Assert-Equal -Name 'dedup kept prompt_queued at exactly one' `
        -Actual $queued.Count -Expected 1

    Write-Host ''
    Write-Host 'E2E ORCHESTRATION: PASS - all scenarios succeeded.'
    exit 0
}
catch {
    Write-Host "E2E ORCHESTRATION FAILED: $($_.Exception.Message)"
    if ($script:Listener -and -not $script:Listener.HasExited) {
        Write-Host "Listener stderr ($stderrLog):"
        Get-Content $stderrLog -ErrorAction SilentlyContinue | Select-Object -Last 20
    }
    exit 1
}
finally {
    if ($script:Listener -and -not $script:Listener.HasExited) {
        # Graceful first (SIGTERM on POSIX): uvicorn runs the lifespan shutdown.
        $script:Listener | Stop-Process -ErrorAction SilentlyContinue
        if (-not $script:Listener.WaitForExit(10000)) {
            $script:Listener | Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Host 'listener did not exit gracefully; force-killed.' -ForegroundColor Yellow
        }
    }
    if (Test-Path $logDir) { Remove-Item -Recurse -Force $logDir -ErrorAction SilentlyContinue }
    if ($script:EnvBackup) { Restore-RunEnvironment }
}
