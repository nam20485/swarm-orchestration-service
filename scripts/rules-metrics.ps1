#Requires -Version 7.0
<#
.SYNOPSIS
  Rules-loading metrics: did the agent actually read the .agents/rules/ files its own
  table of contents pointed at, and did any canary token appear without a read behind it?

.DESCRIPTION
  Qwen Code never loads `.agents/rules/` as context (`.agents/skills/` IS a scanned
  skills root — see .agents/rules/qwen-code-docs.md), so the `## Memory and Rules`
  TOC in AGENTS.md is progressive disclosure by convention only: the
  outline is in context, the rule bodies are not. Two user-scope hooks write ground truth to
  ~/.qwen/metrics/:
    instructions-loaded.jsonl  <- InstructionsLoaded  (context files actually injected)
    rule-reads.jsonl           <- PostToolUse/read_file (rule bodies actually read)
  Each rule file carries a `canary: <colour>-<animal>-<n>` token in a trailing HTML comment and
  nowhere in the AGENTS.md preview, so a token in agent output is only explicable by a read.

  NOTE ON CONTAMINATION: any session in which the canary registry or the tokens themselves were
  displayed cannot certify a canary recital (the model could repeat it from the transcript). Those
  sessions are excluded from the fabrication audit by -ExcludedSession, and probes must be run in a
  fresh session rooted in the repo. The registry lives outside the repo tree on purpose.

.PARAMETER Repo
  Repository to report on. Defaults to this script's repo root.

.PARAMETER Days
  Only count events newer than N days. Default 1.

.PARAMETER AuditFabrication
  Scan this repo's session transcripts for canary tokens and flag any token that appeared without
  a logged read of its file in the same session, plus any negative-control token (which must never
  appear at all).

.EXAMPLE
  pwsh scripts/rules-metrics.ps1
  pwsh scripts/rules-metrics.ps1 -Days 7 -AuditFabrication
#>
[CmdletBinding()]
param(
  [string] $Repo = (Split-Path -Parent $PSScriptRoot),
  [double] $Days = 1,
  [switch] $AuditFabrication,
  [string[]] $ExcludedSession = @(),
  [string] $MetricsDir = "$HOME/.qwen/metrics",
  [string] $Registry = "$HOME/.qwen/metrics/canary-registry.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoPath = (Resolve-Path -LiteralPath $Repo).Path
$slug = ($repoPath -replace '[/\\]', '-')
$cutoff = (Get-Date).ToUniversalTime().AddDays(-$Days)

function Read-Jsonl {
  param([string] $Path)
  if (-not (Test-Path -LiteralPath $Path)) { return @() }
  Get-Content -LiteralPath $Path -Encoding utf8 |
    Where-Object { $_.Trim().Length -gt 0 } |
    ForEach-Object { try { $_ | ConvertFrom-Json } catch { } }
}

# StrictMode-safe property guards: one malformed row in the append-only hook
# logs must be skipped, not fatal to the whole report (PropertyNotFoundException
# under Set-StrictMode -Version Latest + $ErrorActionPreference Stop).
$loaded = @(@(Read-Jsonl (Join-Path $MetricsDir 'instructions-loaded.jsonl')) |
  Where-Object { $_.PSObject.Properties['cwd'] -and $_.cwd -eq $repoPath })
$reads = @(@(Read-Jsonl (Join-Path $MetricsDir 'rule-reads.jsonl')) |
  Where-Object { $_.PSObject.Properties['cwd'] -and $_.cwd -eq $repoPath })

# Null-safe window filter: `-as` yields $null for a null, absent, or
# non-date ts — the row simply misses the window instead of throwing
# (a bare [datetime] cast aborts the whole report under ErrorActionPreference
# Stop, exactly what these guards exist to prevent).
function In-Window { param($items) @(@($items) | Where-Object {
    $ts = if ($_.PSObject.Properties['ts']) { $_.ts -as [datetime] }
    $null -ne $ts -and $ts.ToUniversalTime() -ge $cutoff }) }
# An @() returned from a function collapses to $null on assignment, so re-wrap here: under
# Set-StrictMode a bare $null.Count is an error, not 0.
$loadedW = @(In-Window $loaded)
$readsW = @(In-Window $reads)

Write-Host "repo            : $repoPath"
Write-Host "window          : last $Days day(s)"
# Same PSObject.Properties guard as the consult table below: member-mode
# ForEach-Object (`ForEach-Object file`) throws PropertyNotFoundException
# under StrictMode on a row missing the property — one malformed hook-log
# row must be skipped, not abort the whole report.
Write-Host "context loads   : $($loadedW.Count)  (distinct files $(@($loadedW | ForEach-Object { if ($_.PSObject.Properties['file']) { $_.file } } | Sort-Object -Unique).Count))"
Write-Host "rule reads      : $($readsW.Count)  (distinct sessions $(@($readsW | ForEach-Object { if ($_.PSObject.Properties['session']) { $_.session } } | Sort-Object -Unique).Count))"

# --- Was the entry point that carries the TOC actually in context? ---
Write-Host "`n== Context files injected into sessions (proof the TOC was available) =="
$loadedW |
  Where-Object { $_.PSObject.Properties['file'] -and $_.file } |
  Group-Object file |
  Sort-Object Count -Descending |
  ForEach-Object {
    [pscustomobject]@{ File = Split-Path $_.Name -Leaf; Loads = $_.Count; Reason = ((@($_.Group | ForEach-Object { if ($_.PSObject.Properties['load_reason']) { $_.load_reason } }) | Sort-Object -Unique) -join ',') }
  } | Format-Table -AutoSize

# --- Per-rule-file consult table ---
$ruleRoot = Join-Path $repoPath '.agents/rules'
$registryObj = $null
if (Test-Path -LiteralPath $Registry) { $registryObj = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json }

Write-Host "`n== Rule files under .agents/rules : consulted vs never read =="
$rows = @()
if (Test-Path -LiteralPath $ruleRoot) {
  $rows = @(Get-ChildItem -LiteralPath $ruleRoot -Recurse -Filter '*.md' -Force | ForEach-Object {
      $rel = $_.FullName.Substring($ruleRoot.Length + 1) -replace '\\', '/'
      $hits = @($readsW | Where-Object { $_.PSObject.Properties['file'] -and $_.file -and $_.file.Replace('\', '/').EndsWith("/.agents/rules/$rel") })
      $canary = ''
      if ($registryObj -and $registryObj.PSObject.Properties['rules']) {
        $val = $registryObj.rules.PSObject.Properties[$rel]
        if ($val) { $canary = $val.Value }
      }
      [pscustomobject]@{
        Rule     = $rel
        Canary   = $canary
        Reads    = $hits.Count
        Sessions = (@($hits | ForEach-Object { if ($_.PSObject.Properties['session']) { $_.session } } | Sort-Object -Unique)).Count
        LastRead = if ($hits.Count) { (($hits | ForEach-Object { [datetime]$_.ts } | Sort-Object)[-1]).ToString('MM-dd HH:mm') } else { '-' }
        Status   = if ($rel -like '*unreferenced*') { 'DECOY(must stay unread)' } elseif ($hits.Count) { 'consulted' } else { 'NEVER READ' }
      }
    })
}
$rows | Format-Table -AutoSize -Wrap

$neverRead = @($rows | Where-Object { $_.Status -eq 'NEVER READ' })
$consulted = @($rows | Where-Object { $_.Status -eq 'consulted' })
# Decoy untouched-ness must come from the decoy rows' own Reads column: decoys
# never enter the consulted/NEVER READ buckets, so a subtraction over statuses
# would report every decoy present as untouched — a static file count, not a
# violation signal.
$decoyRows = @($rows | Where-Object { $_.Status -like 'DECOY*' })
$decoyRead = @($decoyRows | Where-Object { $_.Reads -gt 0 })
$decayed = $decoyRows.Count - $decoyRead.Count
if ($consulted.Count + $neverRead.Count -gt 0) {
  $rate = [math]::Round(100.0 * $consulted.Count / ($consulted.Count + $neverRead.Count), 1)
  Write-Host "`nconsult breadth   : $rate % of TOC-listed rule files read at least once in window"
  Write-Host "never read        : $($neverRead.Count)  ->  $(($neverRead | ForEach-Object { Split-Path $_.Rule -Leaf }) -join ', ')"
  Write-Host "decoys untouched  : $decayed"
  if ($decoyRead.Count) {
    Write-Host "!! DECOY READ     : $($decoyRead.Count)  ->  $(($decoyRead | ForEach-Object { Split-Path $_.Rule -Leaf }) -join ', ')" -ForegroundColor Yellow
  }
}

$contam = @(@(Read-Jsonl (Join-Path $MetricsDir 'registry-contamination.jsonl')) |
  Where-Object { $_.PSObject.Properties['cwd'] -and $_.cwd -eq $repoPath -and $_.PSObject.Properties['session'] -and $_.PSObject.Properties['ts'] -and $_.PSObject.Properties['file'] })
if ($contam.Count) {
  Write-Host "`n!! REGISTRY CONTAMINATION: the answer key was read in $(@($contam | ForEach-Object session | Sort-Object -Unique).Count) session(s); canary recitals from those sessions prove nothing:" -ForegroundColor Yellow
  $contam | ForEach-Object { Write-Host "   $($_.ts)  session=$($_.session)  $($_.file)" }
}

# --- Fabrication audit ---
if ($AuditFabrication) {
  Write-Host "`n== Fabrication audit (transcript scan) =="
  $chatDir = Join-Path $HOME ".qwen/projects/$slug/chats"
  if (-not (Test-Path -LiteralPath $chatDir)) {
    Write-Host "   no transcripts for this repo yet at $chatDir"
  }
  else {
    $tokens = @{}
    if ($registryObj -and $registryObj.PSObject.Properties['rules']) {
      $registryObj.rules.PSObject.Properties | ForEach-Object { $tokens[$_.Value] = $_.Name }
    }
    if ($registryObj -and $registryObj.PSObject.Properties['negative_controls']) {
      $registryObj.negative_controls.PSObject.Properties |
        Where-Object { $_.Name -ne '_purpose' } |
        ForEach-Object { $tokens[$_.Value] = "!DECOY! $($_.Name)" }
    }
    $findings = @()
    Get-ChildItem -LiteralPath $chatDir -Filter '*.jsonl' |
      Where-Object { $ExcludedSession -notcontains $_.BaseName } |
      ForEach-Object {
        $session = $_.BaseName
        $text = Get-Content -LiteralPath $_.FullName -Raw -Encoding utf8
        foreach ($k in $tokens.Keys) {
          if ($text -match [regex]::Escape($k)) {
            $fileOfToken = $tokens[$k]
            # Anchor the read credit the same way the consult table does: a
            # basename-only match would credit a read of any same-named file.
            $relOfToken = $fileOfToken -replace '^!DECOY! ', ''
            $hasRead = @($reads | Where-Object {
                $_.PSObject.Properties['session'] -and $_.session -eq $session -and
                $_.PSObject.Properties['file'] -and $_.file -and $_.file.Replace('\', '/').EndsWith("/.agents/rules/$relOfToken")
              }).Count -gt 0
            $kind = if ($fileOfToken -like '!DECOY!*') { 'DECOY-APPEARED (over-load or fabrication)' }
            elseif (-not $hasRead) { 'UNSUPPORTED (token with no logged read)' }
            else { 'supported' }
            $findings += [pscustomobject]@{ Session = $session; Token = $k; Rule = $fileOfToken; Verdict = $kind }
          }
        }
      }
    if ($tokens.Count -eq 0) { Write-Host '   no canary tokens loaded (registry missing or empty) — transcript scan not run' -ForegroundColor Yellow }
    elseif (-not $findings.Count) { Write-Host '   clean: no canary token appeared in any scanned transcript without a read behind it' }
    else { $findings | Where-Object { $_.Verdict -ne 'supported' } | Format-Table -AutoSize }
  }
}
