<#
.SYNOPSIS
    注册 yanwai:// 协议，让浏览器可以直接唤起「言外」桌面端。

.DESCRIPTION
    只写入当前用户的 HKCU\Software\Classes\yanwai，不需要管理员权限。
    注册后，介绍页上的「启动桌面端」按钮会通过 web\launch-desktop.vbs
    以无控制台窗口的方式运行 .venv\Scripts\pythonw.exe run.py。

.PARAMETER Remove
    移除已注册的协议。

.PARAMETER DryRun
    只打印将要写入的注册表位置和启动命令，不做任何修改。

.EXAMPLE
    .\web\register-protocol.ps1
    .\web\register-protocol.ps1 -Remove
    .\web\register-protocol.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$launcher = Join-Path $projectRoot "web\launch-desktop.vbs"
$pythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$iconPath = Join-Path $projectRoot "assets\app.ico"
if (-not (Test-Path $iconPath)) { $iconPath = $pythonw }
$protocolKey = "HKCU:\Software\Classes\yanwai"
$command = 'wscript.exe "' + $launcher + '"'

if ($Remove) {
    if ($DryRun) {
        Write-Host "[dry-run] 将移除 $protocolKey"
        exit 0
    }
    if (Test-Path $protocolKey) {
        Remove-Item -Path $protocolKey -Recurse -Force
        Write-Host "已移除 yanwai:// 协议。" -ForegroundColor Green
    } else {
        Write-Host "yanwai:// 协议尚未注册，无需移除。" -ForegroundColor DarkGray
    }
    exit 0
}

if (-not (Test-Path $launcher)) {
    Write-Host "未找到启动器：$launcher" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $pythonw)) {
    Write-Host "未找到 .venv\Scripts\pythonw.exe。" -ForegroundColor Yellow
    Write-Host "请先在项目根目录运行 .\setup.ps1。" -ForegroundColor Yellow
    exit 1
}

if ($DryRun) {
    Write-Host "[dry-run] 协议：yanwai://"
    Write-Host "[dry-run] 注册表：$protocolKey"
    Write-Host "[dry-run] 图标：$iconPath,0"
    Write-Host "[dry-run] 命令：$command"
    exit 0
}

New-Item -Path $protocolKey -Force | Out-Null
Set-Item -Path $protocolKey -Value "URL:言外 Protocol"
New-ItemProperty -Path $protocolKey -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null

New-Item -Path "$protocolKey\DefaultIcon" -Force | Out-Null
Set-Item -Path "$protocolKey\DefaultIcon" -Value "$iconPath,0"

New-Item -Path "$protocolKey\shell\open\command" -Force | Out-Null
Set-Item -Path "$protocolKey\shell\open\command" -Value $command

Write-Host ""
Write-Host "已注册 yanwai:// → 言外" -ForegroundColor Green
Write-Host "现在回到介绍页，点击「启动桌面端」即可。" -ForegroundColor Gray
Write-Host "移除注册：.\web\register-protocol.ps1 -Remove" -ForegroundColor DarkGray
