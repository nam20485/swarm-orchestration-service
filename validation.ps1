#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Repository validation script (build, scan, test).

.DESCRIPTION
    Mirrors the CI/CD pipeline exactly. Run locally before committing.
    See .agents/rules/validation.md for the policy this implements.

.PARAMETER Step
    Which step(s) to run: build, scan, test, or all (default).

.PARAMETER CoverageThreshold
    Minimum code coverage percentage (default 85).

.PARAMETER SkipHtml
    Skip HTML coverage report generation.

.PARAMETER SkipDotnet
    Skip the .NET branch (SwarmSandbox solution build/test/coverage) for
    environments without the .NET SDK. The Pester flow is unaffected.

.PARAMETER SkipPython
    Skip the Python branch (webhook-receiver pytest/coverage) for
    environments without python3. The Pester and .NET flows are unaffected.

.EXAMPLE
    ./validation.ps1
    ./validation.ps1 -Step test
    ./validation.ps1 -Step dotnet
    ./validation.ps1 -CoverageThreshold 90 -SkipHtml
#>
[CmdletBinding()]
param(
    [ValidateSet('build', 'scan', 'test', 'dotnet', 'python', 'all')]
    [string]$Step = 'all',

    [int]$CoverageThreshold = 85,

    [switch]$SkipHtml,

    [switch]$SkipDotnet,

    [switch]$SkipPython
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot

$dotnetToolsPath = Join-Path $HOME '.dotnet' 'tools'
if (($env:PATH -notlike "*$dotnetToolsPath*") -and (Test-Path $dotnetToolsPath)) {
    $env:PATH = "$dotnetToolsPath$([IO.Path]::PathSeparator)$env:PATH"
}

# Repo convention: markdownlint/gitleaks/actionlint/reportgenerator live in ~/.local/bin.
$localBinPath = Join-Path $HOME '.local' 'bin'
if (($env:PATH -notlike "*$localBinPath*") -and (Test-Path $localBinPath)) {
    $env:PATH = "$localBinPath$([IO.Path]::PathSeparator)$env:PATH"
}

function Install-RequiredModule {
    param([string]$Name, [version]$MinVersion)
    $mod = Get-Module -ListAvailable $Name | Where-Object { $_.Version -ge $MinVersion } | Select-Object -First 1
    if (-not $mod) {
        Write-Host "Installing $Name (>= $MinVersion)..." -ForegroundColor Cyan
        Install-Module $Name -MinimumVersion $MinVersion -Force -Scope CurrentUser -AcceptLicense -AllowClobber
    }
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Step-Build {
    Write-Host "`n=== BUILD ===" -ForegroundColor Cyan

    if (-not (Test-CommandAvailable 'markdownlint-cli2')) {
        throw "markdownlint-cli2 not found. Install: npm install -g markdownlint-cli2"
    }

    Write-Host "Running markdownlint..." -ForegroundColor Gray
    & markdownlint-cli2
    if ($LASTEXITCODE -ne 0) { throw "markdownlint failed with exit code $LASTEXITCODE" }

    Write-Host "Validating relative Markdown links..." -ForegroundColor Gray
    $linkErrors = @()
    $mdFiles = @('README.md', 'AGENTS.md')
    foreach ($file in $mdFiles) {
        $fullPath = Join-Path $repoRoot $file
        if (-not (Test-Path $fullPath)) { continue }
        $content = Get-Content $fullPath -Raw
        $fileDir = Split-Path $fullPath -Parent
        $linkMatches = [regex]::Matches($content, '\[([^\]]*)\]\(([^)]+)\)')
        foreach ($m in $linkMatches) {
            $linkPath = $m.Groups[2].Value
            if ($linkPath -match '^(https?|mailto):') { continue }
            if ($linkPath -match '^#') { continue }
            $filePath = $linkPath -replace '#.*$', ''
            if ([string]::IsNullOrWhiteSpace($filePath)) { continue }
            $resolved = (Resolve-Path (Join-Path $fileDir $filePath) -ErrorAction SilentlyContinue)
            if (-not $resolved) {
                $linkErrors += "$file -> $linkPath"
            }
        }
    }
    if ($linkErrors.Count -gt 0) {
        throw "Broken relative links found:`n$($linkErrors -join "`n")"
    }

    Write-Host "Build passed." -ForegroundColor Green
}

function Step-Scan {
    Write-Host "`n=== SCAN ===" -ForegroundColor Cyan

    Install-RequiredModule -Name 'PSScriptAnalyzer' -MinVersion '1.20.0'

    $scanDirs = @(
        (Join-Path $repoRoot '.agents/skills/gh-issue-tracking-init/scripts'),
        (Join-Path $repoRoot '.agents/skills/update-powershell-standard/scripts'),
        (Join-Path $repoRoot 'scripts')
    )

    Write-Host "Running PSScriptAnalyzer (Error severity)..." -ForegroundColor Gray
    $errors = @()
    foreach ($dir in $scanDirs) {
        if (Test-Path $dir) {
            $errors += @(Invoke-ScriptAnalyzer -Path $dir -Recurse -Severity Error -ErrorAction SilentlyContinue)
        }
    }
    if ($errors.Count -gt 0) {
        $msg = ($errors | ForEach-Object { "  $($_.ScriptName):$($_.Line) $($_.Message)" }) -join "`n"
        throw "PSScriptAnalyzer found $($errors.Count) error(s):`n$msg"
    }

    $warnings = @()
    foreach ($dir in $scanDirs) {
        if (Test-Path $dir) {
            $warnings += @(Invoke-ScriptAnalyzer -Path $dir -Recurse -Severity Warning -ErrorAction SilentlyContinue)
        }
    }
    if ($warnings.Count -gt 0) {
        Write-Host "PSScriptAnalyzer: $($warnings.Count) warning(s) (non-blocking)" -ForegroundColor Yellow
    }

    if (-not (Test-CommandAvailable 'gitleaks')) {
        throw "gitleaks not found. Install: https://github.com/gitleaks/gitleaks/releases"
    }
    Write-Host "Running gitleaks..." -ForegroundColor Gray
    & gitleaks detect --source $repoRoot --config (Join-Path $repoRoot '.gitleaks.toml') --no-banner --redact
    if ($LASTEXITCODE -ne 0) { throw "gitleaks found leaks (exit code $LASTEXITCODE)" }

    Write-Host "Scan passed." -ForegroundColor Green
}

function Step-Test {
    Write-Host "`n=== TEST ===" -ForegroundColor Cyan

    Install-RequiredModule -Name 'Pester' -MinVersion '5.0.0'

    $testPaths = @(
        (Join-Path $repoRoot '.agents/skills/gh-issue-tracking-init/scripts/tests'),
        (Join-Path $repoRoot '.agents/skills/update-powershell-standard/scripts/tests'),
        (Join-Path $repoRoot '.agents/skills/swarm/scripts/tests')
    )
    $coveragePaths = @(
        (Join-Path $repoRoot '.agents/skills/gh-issue-tracking-init/scripts'),
        (Join-Path $repoRoot '.agents/skills/update-powershell-standard/scripts'),
        (Join-Path $repoRoot '.agents/skills/swarm/scripts')
    )
    $coverageFile = Join-Path $repoRoot 'coverage.xml'

    $cfg = New-PesterConfiguration
    $cfg.Run.Path = $testPaths
    $cfg.CodeCoverage.Enabled = $true
    $cfg.CodeCoverage.Path = $coveragePaths
    $cfg.CodeCoverage.OutputFormat = 'JaCoCo'
    $cfg.CodeCoverage.OutputPath = $coverageFile
    $cfg.Output.Verbosity = 'Minimal'
    $cfg.Run.PassThru = $true

    Write-Host "Running Pester tests..." -ForegroundColor Gray
    $result = Invoke-Pester -Configuration $cfg

    if ($result.FailedCount -gt 0) {
        throw "Pester: $($result.FailedCount) test(s) failed (out of $($result.TotalCount))"
    }

    Write-Host "Pester: $($result.PassedCount)/$($result.TotalCount) tests passed" -ForegroundColor Green

    $coveragePercent = [math]::Round($result.CodeCoverage.CoveragePercent, 2)
    $executed = $result.CodeCoverage.CommandsExecutedCount
    $analyzed = $result.CodeCoverage.CommandsAnalyzedCount
    $color = if ($coveragePercent -ge $CoverageThreshold) { 'Green' } else { 'Red' }
    Write-Host "Coverage: $coveragePercent% ($executed/$analyzed commands)" -ForegroundColor $color

    if ($coveragePercent -lt $CoverageThreshold) {
        $needed = [math]::Ceiling($CoverageThreshold * $analyzed / 100)
        throw "Coverage $coveragePercent% is below threshold $CoverageThreshold% (need $needed executed, have $executed)"
    }

    if (-not $SkipHtml) {
        Write-Host "Generating HTML coverage report..." -ForegroundColor Gray
        $rgInstalled = (dotnet tool list -g 2>$null) -match 'dotnet-reportgenerator-globaltool'
        if (-not $rgInstalled) {
            Write-Host "Installing ReportGenerator..." -ForegroundColor Gray
            dotnet tool install --global dotnet-reportgenerator-globaltool --version 5.5.10
            if ($LASTEXITCODE -ne 0) { throw "Failed to install ReportGenerator" }
        }

        $htmlDir = Join-Path $repoRoot 'coverage-html'
        & reportgenerator "-reports:$coverageFile" "-targetdir:$htmlDir" "-reporttypes:Html"
        if ($LASTEXITCODE -ne 0) { throw "ReportGenerator failed with exit code $LASTEXITCODE" }
        Write-Host "HTML coverage report generated at coverage-html/" -ForegroundColor Green
    }

    Write-Host "Test passed." -ForegroundColor Green
}

function Ensure-ReportGenerator {
    # Same 5.5.10 pin as the Pester HTML step (ci-cd.md: strict version pinning).
    $rgInstalled = (dotnet tool list -g 2>$null) -match 'dotnet-reportgenerator-globaltool'
    if (-not $rgInstalled) {
        Write-Host "Installing ReportGenerator..." -ForegroundColor Gray
        dotnet tool install --global dotnet-reportgenerator-globaltool --version 5.5.10
        if ($LASTEXITCODE -ne 0) { throw "Failed to install ReportGenerator" }
    }
}

function Step-Dotnet {
    if ($SkipDotnet) {
        Write-Host "`n=== DOTNET (skipped by -SkipDotnet) ===" -ForegroundColor Yellow
        return
    }

    if (-not (Test-CommandAvailable 'dotnet')) {
        throw ".NET SDK not found. Install the .NET 10 SDK, or run validation.ps1 with -SkipDotnet."
    }

    Write-Host "`n=== DOTNET (SwarmSandbox build/test/coverage) ===" -ForegroundColor Cyan

    $sln = Join-Path $repoRoot 'src/SwarmSandbox/SwarmSandbox.sln'
    if (-not (Test-Path $sln)) { throw "Solution not found: $sln" }
    $resultsDir = Join-Path $repoRoot 'TestResults/dotnet'
    if (Test-Path $resultsDir) { Remove-Item -Recurse -Force $resultsDir }

    Write-Host "Building SwarmSandbox solution..." -ForegroundColor Gray
    & dotnet build $sln
    if ($LASTEXITCODE -ne 0) { throw "dotnet build failed with exit code $LASTEXITCODE" }

    Write-Host "Running SwarmSandbox tests with XPlat Code Coverage..." -ForegroundColor Gray
    & dotnet test $sln --no-build --collect:"XPlat Code Coverage" --results-directory $resultsDir
    if ($LASTEXITCODE -ne 0) { throw "dotnet test failed with exit code $LASTEXITCODE" }

    $coverageFiles = @(Get-ChildItem $resultsDir -Filter 'coverage.cobertura.xml' -Recurse)
    if ($coverageFiles.Count -eq 0) { throw "No coverage.cobertura.xml produced under $resultsDir" }

    # Aggregate line coverage over the SwarmSandbox product assemblies; exclude
    # the Tests assembly itself (nothing else is excluded).
    $totalCovered = 0
    $totalValid = 0
    $perAssembly = foreach ($file in $coverageFiles) {
        $doc = [xml](Get-Content $file.FullName -Raw)
        $productPackages = @($doc.coverage.packages.package | Where-Object { $_.name -notmatch 'Tests$' })
        foreach ($pkg in $productPackages) {
            $lines = @($pkg.SelectNodes('.//line'))
            $valid = $lines.Count
            $hit = @($lines | Where-Object { [int]$_.hits -gt 0 }).Count
            $totalValid += $valid
            $totalCovered += $hit
            [pscustomobject]@{
                Assembly = $pkg.name
                Covered  = $hit
                Valid    = $valid
                Percent  = if ($valid -gt 0) { [math]::Round(100 * $hit / $valid, 2) } else { 0 }
            }
        }
    }

    if ($totalValid -eq 0) { throw "Cobertura report(s) contained no instrumented lines" }
    $coveragePercent = [math]::Round(100 * $totalCovered / $totalValid, 2)
    $color = if ($coveragePercent -ge $CoverageThreshold) { 'Green' } else { 'Red' }
    Write-Host "SwarmSandbox coverage: $coveragePercent% ($totalCovered/$totalValid lines)" -ForegroundColor $color
    foreach ($entry in $perAssembly) {
        Write-Host "  $($entry.Assembly): $($entry.Percent)% ($($entry.Covered)/$($entry.Valid) lines)"
    }

    if (-not $SkipHtml) {
        # Merge the cobertura into the existing coverage-html/ output alongside
        # the Pester JaCoCo report (if it exists), reusing the 5.5.10 pin.
        Ensure-ReportGenerator
        $htmlDir = Join-Path $repoRoot 'coverage-html'
        $reports = @()
        $pesterCoverage = Join-Path $repoRoot 'coverage.xml'
        if (Test-Path $pesterCoverage) { $reports += $pesterCoverage }
        $reports += @($coverageFiles | ForEach-Object { $_.FullName })
        & reportgenerator "-reports:$($reports -join ';')" "-targetdir:$htmlDir" "-reporttypes:Html"
        if ($LASTEXITCODE -ne 0) { throw "ReportGenerator failed with exit code $LASTEXITCODE" }
        Write-Host "Merged HTML coverage report generated at coverage-html/" -ForegroundColor Green
    }

    # Gate runs after the HTML merge so coverage-html/ exists even on failure.
    if ($coveragePercent -lt $CoverageThreshold) {
        $breakdown = ($perAssembly | ForEach-Object {
            "  $($_.Assembly): $($_.Covered)/$($_.Valid) lines ($($_.Percent)%)"
        }) -join "`n"
        throw "SwarmSandbox coverage $coveragePercent% is below threshold $CoverageThreshold%. Per assembly:`n$breakdown"
    }

    Write-Host "Dotnet passed." -ForegroundColor Green
}

function Step-Python {
    if ($SkipPython) {
        Write-Host "`n=== PYTHON (skipped by -SkipPython) ===" -ForegroundColor Yellow
        return
    }

    $serviceDir = Join-Path $repoRoot 'src/webhook_receiver'
    if (-not (Test-Path $serviceDir)) {
        Write-Host "`n=== PYTHON (skipped: src/webhook_receiver not found) ===" -ForegroundColor Yellow
        return
    }

    $pythonCmd = $null
    foreach ($candidate in @('python3', 'python')) {
        if (Test-CommandAvailable $candidate) { $pythonCmd = $candidate; break }
    }
    if (-not $pythonCmd) {
        Write-Host "`n=== PYTHON (skipped: python3 not found; install Python 3.12+ to run the webhook-receiver suite) ===" -ForegroundColor Yellow
        return
    }

    Write-Host "`n=== PYTHON (webhook-receiver pytest/coverage) ===" -ForegroundColor Cyan

    $venvDir = Join-Path $repoRoot '.venv'
    $venvPython = if ($IsWindows) { Join-Path $venvDir 'Scripts' 'python.exe' } else { Join-Path $venvDir 'bin' 'python' }
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating python venv at .venv and installing requirements-dev.txt..." -ForegroundColor Gray
        & $pythonCmd -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "python venv creation failed with exit code $LASTEXITCODE" }
        & $venvPython -m pip install --quiet --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
        & $venvPython -m pip install --quiet -r (Join-Path $serviceDir 'requirements-dev.txt')
        if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
    }

    Write-Host "Running webhook-receiver pytest suite..." -ForegroundColor Gray
    $coverageJson = Join-Path $repoRoot 'coverage.json'
    $covModules = @(
        'webhook_receiver.acp_host',
        'webhook_receiver.acp_policy',
        'webhook_receiver.acp_smoke',
        'webhook_receiver.app',
        'webhook_receiver.config',
        'webhook_receiver.event_store',
        'webhook_receiver.filters',
        'webhook_receiver.github',
        'webhook_receiver.prompt_builder',
        'webhook_receiver.prompt_queue',
        'webhook_receiver.sandbox_bridge'
    )
    $pytestArgs = @('-m', 'pytest', (Join-Path $serviceDir 'tests'), '-q')
    foreach ($mod in $covModules) { $pytestArgs += "--cov=$mod" }
    $pytestArgs += @('--cov-report=term-missing', '--cov-report=json')
    & $venvPython @pytestArgs
    if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path $coverageJson)) { throw "pytest did not produce $coverageJson" }

    $cov = Get-Content $coverageJson -Raw | ConvertFrom-Json -AsHashtable
    $coveragePercent = [math]::Round($cov.totals.percent_covered, 2)
    $color = if ($coveragePercent -ge $CoverageThreshold) { 'Green' } else { 'Red' }
    Write-Host "webhook-receiver coverage: $coveragePercent% ($($cov.totals.covered_lines)/$($cov.totals.num_statements) lines)" -ForegroundColor $color

    if ($coveragePercent -lt $CoverageThreshold) {
        throw "webhook-receiver coverage $coveragePercent% is below threshold $CoverageThreshold%"
    }

    Write-Host "Python passed." -ForegroundColor Green
}

Set-Location $repoRoot

switch ($Step) {
    'build'  { Step-Build }
    'scan'   { Step-Scan }
    'test'   { Step-Test }
    'dotnet' { Step-Dotnet }
    'python' { Step-Python }
    'all'    { Step-Build; Step-Scan; Step-Test; Step-Dotnet; Step-Python }
}

Write-Host "`nAll validation steps passed." -ForegroundColor Green
