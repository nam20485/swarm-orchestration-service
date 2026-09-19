#!/usr/bin/env pwsh
#requires -Version 7.0
<#
.SYNOPSIS
Pester 5 tests for scripts/logging.ps1
#>

BeforeAll {
    $script:LoggingPath = Join-Path $PSScriptRoot '..' 'scripts' 'logging.ps1'
    . $script:LoggingPath
}

Describe 'Start-RunLog' {
    It 'Creates a log file and returns its path' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            $logPath | Should -Not -BeNullOrEmpty
            Test-Path -LiteralPath $logPath | Should -BeTrue
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Writes an init entry as the first line' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            $lines = @(Get-Content -LiteralPath $logPath)
            $lines | Should -HaveCount 1
            $entry = $lines[0] | ConvertFrom-Json
            $entry.step | Should -Be 'init'
            $entry.level | Should -Be 'INFO'
            $entry.message | Should -Match 'Run started'
            $entry.data.runName | Should -Be 'test-run'
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Creates the log directory if it does not exist' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)" 'subdir'
        try {
            Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Test-Path -LiteralPath $tmpDir | Should -BeTrue
        }
        finally {
            $parent = Split-Path $tmpDir
            if (Test-Path $parent) { Remove-Item $parent -Recurse -Force }
        }
    }
}

Describe 'Write-RunLog' {
    It 'Appends a JSONL entry to the log file' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Write-RunLog -Level 'INFO' -Step 'test-step' -Message 'hello world'
            $lines = Get-Content -LiteralPath $logPath
            $lines | Should -HaveCount 2
            $entry = $lines[1] | ConvertFrom-Json
            $entry.step | Should -Be 'test-step'
            $entry.message | Should -Be 'hello world'
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Includes data bag when provided' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Write-RunLog -Level 'WARN' -Step 'data-test' -Message 'with data' -Data @{ key = 'value' }
            $lines = Get-Content -LiteralPath $logPath
            $entry = $lines[-1] | ConvertFrom-Json
            $entry.data.key | Should -Be 'value'
            $entry.level | Should -Be 'WARN'
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Does nothing when no run log is active' {
        # Reset module state
        . $script:LoggingPath
        # This should not throw
        { Write-RunLog -Level 'INFO' -Step 'orphan' -Message 'no log active' } | Should -Not -Throw
    }
}

Describe 'Complete-RunLog' {
    It 'Writes a completion entry with SUCCESS' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Complete-RunLog -Status 'SUCCESS'
            $lines = Get-Content -LiteralPath $logPath
            $last = $lines[-1] | ConvertFrom-Json
            $last.step | Should -Be 'complete'
            $last.message | Should -Match 'SUCCESS'
            $last.data.elapsedSeconds | Should -BeOfType [double]
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Writes a completion entry with FAILURE and error message' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Complete-RunLog -Status 'FAILURE' -ErrorMessage 'something broke'
            $lines = Get-Content -LiteralPath $logPath
            $last = $lines[-1] | ConvertFrom-Json
            $last.step | Should -Be 'complete'
            $last.level | Should -Be 'ERROR'
            $last.data.error | Should -Be 'something broke'
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }

    It 'Resets state so subsequent Write-RunLog calls are no-ops' {
        $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "pester-log-$(Get-Random)"
        try {
            $logPath = Start-RunLog -LogDir $tmpDir -RunName 'test-run'
            Complete-RunLog -Status 'SUCCESS'
            $linesBefore = (Get-Content -LiteralPath $logPath).Count
            Write-RunLog -Level 'INFO' -Step 'after-complete' -Message 'should be ignored'
            $linesAfter = (Get-Content -LiteralPath $logPath).Count
            $linesAfter | Should -Be $linesBefore
        }
        finally {
            if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        }
    }
}
