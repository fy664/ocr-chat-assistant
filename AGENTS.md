# 言外

Windows 桌面聊天助手，使用 Python、PySide6、PaddleOCR 和 OpenAI-compatible 模型接口。

## 开发入口

- `.\run.ps1` 启动桌面端，`.\run.ps1 --mock-llm` 使用本地模型替身。
- `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q --disable-warnings` 运行测试。
- 当前启动链经由 `app/main.py`、`app/ui/decoder_window.py` 和 `app/analysis/decoder.py`。旧版实时调度和对应设置键用于兼容回归测试。

## 行为约束

- 使用合成对话和模型替身验证采集与解读。画面缓存使用内存，聊天原文、截图和密钥不进日志或版本库。
- 整窗采集时，左栏仅用于识别当前会话。模型上下文使用右侧聊天记录和已确认的消息区画面。
- 解读请求由手动操作或用户启用的自动解读触发。回复建议由用户自行复制、确认和发送。

## 项目文档

- [使用、设置和测试](README.md)
- [项目骨架与数据流](docs/ARCHITECTURE.md)
- [Windows 安装包](packaging/README.md)
