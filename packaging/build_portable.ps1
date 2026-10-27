# 言外 · 构建便携运行时
# 把 Python embeddable + 当前 venv 的 site-packages + 应用源码组合成一个
# 可整体复制/安装的目录。不会复制 .env、config.json、日志或用户凭据。
[CmdletBinding()]
param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\_packaging\portable"),
    [string]$SitePackages = (Join-Path $PSScriptRoot "..\.venv\Lib\site-packages"),
    [string]$PythonVersion = "3.12.0",
    [string]$CacheDir = (Join-Path $PSScriptRoot "..\_packaging\cache"),
    [switch]$SkipCopy
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$CacheDir = [IO.Path]::GetFullPath($CacheDir)
$SitePackages = [IO.Path]::GetFullPath($SitePackages)

if (-not (Test-Path (Join-Path $SitePackages "PySide6"))) {
    throw "site-packages 不完整：$SitePackages（先运行 .\setup.ps1）"
}

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$zipName = "python-$PythonVersion-embed-amd64.zip"
$zipPath = Join-Path $CacheDir $zipName
if (-not (Test-Path $zipPath)) {
    Write-Host "下载 Python $PythonVersion embeddable ..."
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$PythonVersion/$zipName" -OutFile $zipPath -UseBasicParsing
}

if (Test-Path $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
$RuntimeRoot = Join-Path $OutputRoot "runtime"
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
Write-Host "解压 Python embeddable ..."
Expand-Archive -LiteralPath $zipPath -DestinationPath $RuntimeRoot -Force

# 让 embeddable Python 能看到应用源码和 site-packages。
# import site 会处理 site-packages 下的 .pth（PySide6 / paddle 等需要）。
$pth = Join-Path $RuntimeRoot ("python{0}._pth" -f ($PythonVersion -replace '\.\d+$','').Replace('.',''))
if (-not (Test-Path $pth)) {
    $pth = Get-ChildItem $RuntimeRoot -Filter "python*._pth" | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pth) { throw "找不到 embeddable Python 的 _pth 文件" }
$zipStd = "python" + (($PythonVersion -split '\.')[0..1] -join '') + ".zip"
@(
    $zipStd
    "."
    ".."
    "Lib\site-packages"
    "import site"
) | Set-Content -LiteralPath $pth -Encoding ascii

$runtimeSite = Join-Path $RuntimeRoot "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $runtimeSite | Out-Null
if (-not $SkipCopy) {
    Write-Host "复制运行依赖（约 1.4GB，首次较慢）..."
    $excludeDirs = @("__pycache__", ".pytest_cache", "pip", "pytest", "_pytest", "pluggy", "iniconfig")
    $copyArgs = @(
        $SitePackages, $runtimeSite, "/E", "/MT:16", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1"
        "/XD"
    ) + $excludeDirs
    & robocopy @copyArgs | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "robocopy 复制依赖失败：$LASTEXITCODE" }
}

# 复制应用源码与资源；不复制项目根目录的 .env / 配置 / 测试 / 文档 / .venv。
Write-Host "复制应用源码 ..."
foreach ($dir in @("app", "assets")) {
    Copy-Item -LiteralPath (Join-Path $root $dir) -Destination $OutputRoot -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $root "run.py") -Destination $OutputRoot -Force
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination $OutputRoot -Force
# 安装包使用 runtime\pythonw.exe 直接注册协议，不复制源码版 web 启动器。

# 清理 Python 缓存与安装期垃圾；不要清理 dist-info（importlib.metadata / entry points 需要它）。
Write-Host "清理缓存 ..."
Get-ChildItem -LiteralPath $OutputRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $OutputRoot -Recurse -File -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# 便携启动入口（安装包会创建快捷方式，不依赖这个 .cmd）。
@'
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0runtime\pythonw.exe" "%~dp0run.py"
'@ | Set-Content -LiteralPath (Join-Path $OutputRoot "Yanwai.cmd") -Encoding ascii

$size = (Get-ChildItem -LiteralPath $OutputRoot -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("便携运行时已生成：{0}（{1:N2} GB）" -f $OutputRoot, ($size / 1GB))
Write-Host "检查是否存在用户配置/密钥文件："
$forbidden = Get-ChildItem -LiteralPath $OutputRoot -Recurse -File -Force |
    Where-Object { $_.Name -in @(".env", "config.json", "credentials.json") }
if ($forbidden) {
    $forbidden | Select-Object FullName
    throw "发现不应打包的文件，停止。"
} else {
    Write-Host "OK：未发现 .env / config.json / credentials.json。"
}

# 用打包后的 Python 验证依赖（不会加载 OCR 模型）。
$py = Join-Path $RuntimeRoot "python.exe"
Write-Host "验证打包 Python 导入 ..."
Push-Location $OutputRoot
try {
    & $py -c "import sys; print(sys.version); import PySide6, cv2, numpy, openai; from app.ocr.engine import _patch_six_meta_path_importer; _patch_six_meta_path_importer(); import paddle, paddleocr; print('imports OK')"
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "打包运行时导入验证失败" }
