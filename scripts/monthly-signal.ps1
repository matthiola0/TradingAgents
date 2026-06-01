<#
.SYNOPSIS
    Run TradingAgents for this month's BTC + SOL crypto signals (manual,
    once-a-month workflow).

.DESCRIPTION
    Calls weekly_runner.py via run-with-log.ps1 so output is teed to a
    timestamped log under logs\. weekly_runner internally targets the
    first Monday of the current month — re-running mid-month is a no-op
    (memory log dedupes) so safe to run any day.

    DRY RUN by default (no real orders). Pass -Live to actually trade.

    After signals are generated, prints a quick summary of:
      - this month's BTC rating
      - this month's SOL rating
      - last 3 months' history for trend context

.EXAMPLE
    .\scripts\monthly-signal.ps1                # paper / dry run
    .\scripts\monthly-signal.ps1 -Live          # real Binance orders
    .\scripts\monthly-signal.ps1 -Config minimal -PortfolioUsd 500
#>
param(
    [switch]$Live,
    [ValidateSet("full", "minimal")][string]$Config = "full",
    [double]$PortfolioUsd = 1000
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$wrapper = Join-Path $PSScriptRoot "run-with-log.ps1"

# Find conda env python (preferred) or fall back to whatever python is on PATH.
$python = "python"
$condaPy = "$env:USERPROFILE\anaconda3\envs\tradingagents\python.exe"
if (Test-Path $condaPy) { $python = $condaPy }

# Verify Claude OAuth token is wired (must be set at User scope by setx)
if (-not $env:CLAUDE_CODE_OAUTH_TOKEN) {
    $userTok = [System.Environment]::GetEnvironmentVariable("CLAUDE_CODE_OAUTH_TOKEN", "User")
    if ($userTok) {
        $env:CLAUDE_CODE_OAUTH_TOKEN = $userTok
    } else {
        Write-Host "CLAUDE_CODE_OAUTH_TOKEN not set anywhere — see LIVE_TRADING_GUIDE.md" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "=== TradingAgents monthly signal run ===" -ForegroundColor Cyan
Write-Host "Mode      : $(if ($Live) { 'LIVE (real Binance orders)' } else { 'DRY RUN (paper)' })" -ForegroundColor $(if ($Live) { 'Yellow' } else { 'Green' })
Write-Host "Config    : $Config" -ForegroundColor Gray
Write-Host "Paper NAV : `$$PortfolioUsd (ignored in --live mode)" -ForegroundColor Gray
Write-Host "Python    : $python" -ForegroundColor Gray
Write-Host ""

# Build args to weekly_runner.py
$runnerArgs = @("scripts\weekly_runner.py", "--config", $Config)
if ($Live) {
    $runnerArgs += "--live"
} else {
    $runnerArgs += "--portfolio-usd", $PortfolioUsd
}

Push-Location $repo
try {
    & $wrapper $python @runnerArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Host ""
    Write-Host "weekly_runner exited with code $code — check log file above." -ForegroundColor Red
    exit $code
}

# --- Post-run summary: grep last 3 months ratings from memory log ---
Write-Host ""
Write-Host "=== Last 3 months' signals ===" -ForegroundColor Cyan
$memLog = "$env:USERPROFILE\.tradingagents\memory\trading_memory.md"
if (Test-Path $memLog) {
    foreach ($t in "BTC-USD", "SOL-USD") {
        Write-Host ""
        Write-Host "${t}:" -ForegroundColor White
        # Pull the tag lines for this ticker, last 3
        $pattern = "^\[\d{4}-\d{2}-\d{2} \| $([Regex]::Escape($t)) \| "
        $lines = Select-String -Path $memLog -Pattern $pattern -AllMatches |
                 Select-Object -ExpandProperty Line |
                 Select-Object -Last 3
        foreach ($line in $lines) {
            Write-Host "  $line" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "Memory log not found at $memLog" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Run again next month, or any time after the first Monday." -ForegroundColor Green
