# 言外 Yanwai - one-click run (Windows)
# Uses the project .venv and starts the app. Run:  .\run.ps1  (extra args are passed to run.py)
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host ".venv not found. Please run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

& ".\.venv\Scripts\python.exe" run.py @args
exit $LASTEXITCODE
