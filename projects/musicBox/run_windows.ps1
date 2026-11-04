# KIKKER-15 // PowerShell One-Step Launcher for Windows 10/11
# Usage: .\run_windows.ps1 [-Port 8000] [-NoBrowser]
param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Find-Python310 {
    foreach ($candidate in @(
        @{ Exe = "py"; PrefixArgs = @("-3") },
        @{ Exe = "python"; PrefixArgs = @() }
    )) {
        $cmd = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
        if ($null -ne $cmd -and $cmd.Source -notlike "*WindowsApps*") {
            try {
                & $candidate.Exe @($candidate.PrefixArgs) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    return $candidate
                }
            } catch {}
        }
    }
    return $null
}

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $py = Find-Python310
    if ($null -eq $py) {
        Write-Host ""
        Write-Host "[ERROR] Python 3.10 or newer was not found on your Windows PATH." -ForegroundColor Red
        Write-Host "Install Python 3.11+ from https://www.python.org/downloads/windows/ (check 'Add python.exe to PATH'), then re-run." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[Setup] Creating local virtual environment in .venv ..." -ForegroundColor Cyan
    & $py.Exe @($py.PrefixArgs) -m venv ".venv"
}

$ReqFile = Join-Path $PSScriptRoot "requirements.txt"
$StampFile = Join-Path $PSScriptRoot ".venv\.deps_stamp"
$ReqHash = (Get-FileHash -LiteralPath $ReqFile -Algorithm SHA256).Hash
$OldHash = if (Test-Path -LiteralPath $StampFile) { (Get-Content -LiteralPath $StampFile -Raw).Trim() } else { "" }

if ($ReqHash -ne $OldHash) {
    Write-Host "[Setup] Installing / updating Python dependencies ..." -ForegroundColor Cyan
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r $ReqFile
    Set-Content -LiteralPath $StampFile -Value $ReqHash -NoNewline
}

$LaunchArgs = @("launch.py", "--port", "$Port")
if ($NoBrowser) {
    $LaunchArgs += "--no-browser"
}

& $VenvPython @LaunchArgs
