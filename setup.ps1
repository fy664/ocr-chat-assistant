# 言外 Yanwai - one-click setup (Windows)
# Creates .venv and installs all dependencies.
param([string]$IndexUrl)
$ErrorActionPreference = "Stop"

Write-Host "== 言外 Yanwai Setup ==" -ForegroundColor Cyan

# Locate a compatible Python interpreter.
$pyCmd = $null
$pyArgs = @()
$venvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.12", "-3.11")) {
        & py $v --version 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $pyCmd = "py"
            $pyArgs = @($v)
            break
        }
    }
}
if (-not $pyCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pyCmd = "python"
}
if (-not $pyCmd -and -not (Test-Path -LiteralPath $venvPython)) {
    Write-Error "Python not found. Please install Python 3.11/3.12 and retry."
    exit 1
}
$versionCheck = "import struct, sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize('P') == 8 else 1)"
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c $versionCheck
} else {
    & $pyCmd @pyArgs -c $versionCheck
}
if ($LASTEXITCODE -ne 0) { throw "需要 64 位 Python 3.11 或 3.12。" }


# 2. Create .venv
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating virtual environment .venv ..."
    & $pyCmd @pyArgs -m venv (Join-Path $PSScriptRoot ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create .venv"; exit 1 }
} else {
    Write-Host ".venv already exists, reusing."
}

# Install the project's pinned requirements.
$pipArgs = @("-m", "pip", "install", "-r", (Join-Path $PSScriptRoot "requirements.txt"), "--disable-pip-version-check")
if ($IndexUrl) { $pipArgs += @("--index-url", $IndexUrl) }
Write-Host "Installing dependencies ..."
& $venvPython @pipArgs
if ($LASTEXITCODE -ne 0) { Write-Error "Dependency installation failed."; exit 1 }

# 5. Verify core imports
Write-Host "Verifying core imports ..."
& $venvPython -c "import PySide6, mss, PIL, numpy, pydantic, dotenv, openai, keyring, paddle, paddleocr; print('All imports OK'); print('paddle', paddle.__version__); print('paddleocr', paddleocr.__version__)"
if ($LASTEXITCODE -ne 0) { Write-Error "Import verification failed. See messages above."; exit 1 }

Write-Host "== Setup complete. Run .\run.ps1 to start ==" -ForegroundColor Green
