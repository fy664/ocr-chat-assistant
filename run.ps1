# 言外 · 使用项目自带的虚拟环境启动，可从其他目录调用。
$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "找不到 .venv，请运行项目目录下的 setup.ps1。"
}
& $python (Join-Path $PSScriptRoot "run.py") @args
exit $LASTEXITCODE
