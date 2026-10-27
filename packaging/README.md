# 言外 · 打包说明

这里生成两个东西：

1. `_packaging/portable/`：可整体复制的便携运行时（Python embeddable + 依赖 + 源码）；
2. `_packaging/dist/setup.exe`：Windows 安装程序（Inno Setup，按用户安装，无管理员权限）。

## 前置

- 已在项目根目录运行 `.\setup.ps1`（`.venv` 依赖完整）；
- Windows 10/11 x64；
- Inno Setup 6（提供 `ISCC.exe`；本机可放在 `_packaging/inno/ISCC.exe`，或安装到默认目录）；
- 可访问 python.org（首次下载 Python 3.12 embeddable）。

## 构建

```powershell
# 1) 便携运行时（约 1.3GB；会把当前 .venv 的运行依赖复制进去）
.\packaging\build_portable.ps1

# 2) 安装程序（输出到 _packaging\dist\setup.exe）
.\_packaging\inno\ISCC.exe .\packaging\Yanwai.iss
```

如果 `ISCC.exe` 不在 `_packaging/inno`，换成你本机的路径，例如：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" .\packaging\Yanwai.iss
```

## 安全边界

- `build_portable.ps1` 只复制：
  - `app/`、`assets/`、`run.py`、`README.md`
  - 当前 `.venv\Lib\site-packages`（运行依赖）
  - Python embeddable
- **不会复制**：`.env`、`config.json`、`%APPDATA%`、keyring、日志、测试、`.git`、项目配置。
- 脚本会扫描输出目录，发现 `.env` / `config.json` / `credentials.json` 会直接失败。
- 安装包由 Inno Setup 按用户安装到 `%LOCALAPPDATA%\Programs\Yanwai`，注册 `yanwai://` 协议，不写系统级目录。

## 发布

把 `_packaging\dist\setup.exe` 作为 GitHub Release 资产上传即可；不要把安装包提交进 Git（`.gitignore` 已忽略 `_packaging/`）。

当前 GitHub Release：<https://github.com/fy664/ocr-chat-assistant/releases>

## 注意

- 安装程序未做代码签名，SmartScreen 会提示未知发布者。
- 首次读取画面会下载 PaddleOCR 模型（约 100MB）。
- 目标机器需要 Windows 10/11 x64；Paddle 所需 VC++ 运行库通常由 Windows 10/11 自带。
