# 言外 Yanwai - one-click setup (Windows)
# Creates .venv and installs all dependencies. Run:  .\setup.ps1
$ErrorActionPreference = "Stop"

Write-Host "== 言外 Yanwai Setup ==" -ForegroundColor Cyan

# 1. Locate Python (prefer the py launcher with 3.12 / 3.11 / 3.13, fall back to python)
$pyCmd = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.12", "-3.11", "-3.13", "")) {
        $argsToTry = @()
        if ($v) { $argsToTry = @($v, "--version") } else { $argsToTry = @("--version") }
        & py @argsToTry 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $pyCmd = "py"
            if ($v) { $pyArgs = @($v) }
            break
        }
    }
}
if (-not $pyCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pyCmd = "python"
}
if (-not $pyCmd) {
    Write-Error "Python not found. Please install Python 3.11/3.12 and retry."
    exit 1
}
$pyVer = (& $pyCmd @pyArgs --version 2>&1)
Write-Host "Using Python: $pyVer" -ForegroundColor Green

# 2. Create .venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv ..."
    & $pyCmd @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create .venv"; exit 1 }
} else {
    Write-Host ".venv already exists, reusing."
}
$venvPython = ".\.venv\Scripts\python.exe"

# 3. Upgrade pip
Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip --disable-pip-version-check

# 4. Install requirements
# NOTE: the official PyPI CDN can stall on some networks (verified on this
# machine: metadata loads but wheel downloads hang). The Aliyun mirror is
# used as the default index; remove the -i argument if your network is fine
# with pypi.org directly.
$pipIndex = "https://mirrors.aliyun.com/pypi/simple/"
Write-Host "Installing dependencies (this may take a while, PaddlePaddle is large) ..."
& $venvPython -m pip install -r requirements.txt --disable-pip-version-check -i $pipIndex
if ($LASTEXITCODE -ne 0) { Write-Error "Dependency installation failed."; exit 1 }

# 5. Verify core imports
Write-Host "Verifying core imports ..."
& $venvPython -c "import PySide6, mss, PIL, numpy, pydantic, dotenv, openai, keyring, paddle, paddleocr; print('All imports OK'); print('paddle', paddle.__version__); print('paddleocr', paddleocr.__version__)"
if ($LASTEXITCODE -ne 0) { Write-Error "Import verification failed. See messages above."; exit 1 }

Write-Host "== Setup complete. Run .\run.ps1 to start ==" -ForegroundColor Green
