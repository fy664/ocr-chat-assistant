# OCR Chat Assistant — 聊天语义助手（Windows V1）

框选一次聊天区域，程序持续观察：本地 OCR 识别 → 文本变化检测 → 防抖 → 自动语义分析 → 实时更新「表层意思 / 意图 / 情绪 / 潜在诉求 / 回复策略 / 回复建议」。

> 本版本只实现 **Windows Desktop V1**。Android / iOS / 自动发送消息等均不在本轮范围（见 Roadmap）。

---

## 功能

- 全屏半透明**框选聊天区域**（多显示器、DPI 缩放换算为物理像素）
- 固定区域**持续截图**（mss，仅内存，不落盘）
- **本地 PaddleOCR** 识别（中文/英文，含角度分类）
- 文本**标准化 + 指纹变化检测**（OCR 噪声不触发、纯滚动不触发、已分析内容不重复触发）
- **防抖（debounce）**：消息连续变化时等待文本稳定再分析
- **滚动上下文**：增量合并、去重、上限 20 条 / 8000 字符
- **OpenAI-compatible LLM**：Provider/API Key/Base URL/Model/Temperature/Timeout 全可配置
- **结构化输出**：Pydantic Schema 强制校验，JSON 解析失败自动修复重试一次
- **实时机制**：latest-only OCR 队列、max 1 个在途 LLM 请求、generation 防陈旧结果覆盖
- **悬浮窗**：置顶、可拖动、可调整大小
- **OCR 文本编辑**：原始 OCR / 当前分析文本双视图，可修改后「应用并分析」
- **回复建议一键复制**（只复制到剪贴板，不自动粘贴、不自动发送）
- 暂停 / 恢复、清空上下文、重新选择区域（快捷键 `Ctrl+Shift+S`）
- API Key 存储于 **Windows 凭据管理器**（keyring），`.env` 仅作开发回退
- Mock LLM 演示模式：无 API Key 也能体验完整流程（`--mock-llm`）

## 技术架构

```
PySide6 UI（主线程：渲染、状态、编辑）
   │  Qt Signal / Slot
   ▼
PipelineScheduler（主线程编排：状态机 / diff / debounce / generation）
   ├── RegionMonitor（QTimer 采样，mss 截图，仅内存）
   ├── OCRWorkerThread（PaddleOCR 初始化与识别，latest-only 槽位）
   └── LLMWorkerThread（HTTP 请求，max 1 在途）
```

数据流：

```
屏幕区域 → 本地 OCR → 文本 → 用户配置的 LLM API → 结构化分析结果 → 悬浮面板
```

## 项目结构

```
app/
├─ main.py                    # 启动入口（GUI 先开，OCR 模型后台加载）
├─ config/settings.py         # 配置：config.json + keyring + .env，优先级 env > keyring > config
├─ models/schemas.py          # Pydantic 数据模型（AI 输出必须经 Schema 验证）
├─ capture/
│  ├─ screen_capture.py       # mss 截图（内存 RGB ndarray，不写磁盘）
│  ├─ region_selector.py      # 全屏半透明框选 overlay（Enter 确认 / Esc 取消）
│  └─ monitor.py              # 区域定时采样
├─ ocr/
│  ├─ engine.py               # OCREngine 接口 + PaddleOCR 2.x/3.x 适配
│  ├─ preprocess.py           # 轻量预处理（RGB/缩放）
│  ├─ normalize.py            # 空格/换行/重复标点/噪声清理
│  └─ diff.py                 # 指纹 + 行集合变化检测（SAME/SCROLL_ONLY/CHANGED）
├─ context/
│  ├─ models.py               # ContextMessage / ConversationContext
│  ├─ builder.py              # 消息分段 + 左右位置 speaker 启发式
│  └─ manager.py              # 滚动上下文：增量合并、去重、长度限制
├─ llm/
│  ├─ provider.py             # LLMClient 协议 + OpenAICompatibleClient + 错误映射
│  ├─ client.py               # MockLLMClient（测试/演示）
│  ├─ prompt.py               # System Prompt（不读心原则）+ 用户 Prompt 构建
│  └─ parser.py               # JSON 提取 + Pydantic 校验
├─ analysis/
│  ├─ analyzer.py             # Context → Prompt → LLM → AnalysisResult
│  ├─ scheduler.py            # 实时 pipeline 核心（状态机/防抖/generation/latest-only）
│  └─ workers.py              # OCR/LLM 工作线程（信号通信，绝不直接操作 UI）
└─ ui/
   ├─ main_window.py          # 主窗口（悬浮面板）
   ├─ floating_panel.py       # 分析卡片 + 回复建议列表（复制按钮）
   ├─ ocr_editor.py           # 当前聊天 / OCR 原文 / 可编辑分析文本
   ├─ settings_dialog.py      # LLM / 实时 / 界面 设置（连接测试后台线程）
   ├─ status_bar.py           # 状态 + OCR/LLM 忙碌指示 + 更新时间
   └─ styles.py               # QSS 主题
tests/                        # pytest 测试（见「测试」一节）
run.py / run.ps1 / setup.ps1  # 入口与一键脚本
```

## 环境要求

- Windows 10 / 11
- Python 3.11 或 3.12（3.12 已验证，见下）
- 可访问互联网（首次运行下载 PaddleOCR 模型 ~20MB；LLM API 需网络）

**本机实际验证过的版本组合（Windows 11 Pro / 2026-09）：**

| 组件 | 版本 |
|---|---|
| Python | 3.12.0（64-bit） |
| PySide6 | 6.11.2 |
| mss | 10.2.0 |
| Pillow | 12.3.0 |
| numpy | 2.5.3 |
| pydantic | 2.13.5 |
| openai | 3.17.0 |
| python-dotenv | 1.2.3 |
| keyring | 25.7.0 |
| pytest | 9.1.1 |
| paddlepaddle | 3.3.1（CPU） |
| paddleocr | 3.7.0（PP-OCRv6 模型） |

## 安装

```powershell
.\setup.ps1
```

脚本会：检查 Python（优先 `py -3.12`）→ 创建 `.venv` → 升级 pip → 安装 `requirements.txt` → 验证核心 import。

> 网络说明：脚本默认使用阿里云 PyPI 镜像（`mirrors.aliyun.com`）——本机验证直连 pypi.org 时元数据正常但 wheel 下载会卡死。如你的网络可直连 PyPI，删除 `setup.ps1` 中 pip 命令的 `-i` 参数即可。

若需要 GPU 版 PaddlePaddle，请自行将 `.venv` 中的 `paddlepaddle`（CPU）替换为对应的 GPU wheel，再安装 `paddleocr`。

## 运行

```powershell
.\run.ps1                 # 使用项目 .venv 启动
# 或
python run.py             # 已激活 .venv 时
```

附加参数：

```powershell
.\run.ps1 --mock-llm      # 演示模式：内置 Mock LLM，无需 API Key
.\run.ps1 --debug         # 调试日志
```

## 首次配置

1. 启动后点击「设置」；
2. LLM 页填写：

| 字段 | 说明 | 示例 |
|---|---|---|
| Provider 名称 | 任意标记（仅作标识） | `deepseek` / `openai` / `custom` |
| API Key | 密钥，保存到 **Windows 凭据管理器** | `sk-…` |
| Base URL | OpenAI-compatible 接口地址（以 `/v1` 结尾） | `https://api.deepseek.com/v1` |
| Model | 模型名 | `deepseek-chat` / `gpt-4o-mini` |
| Temperature | 建议 0.3（稳定、低随机） | `0.3` |
| Timeout | 秒 | `90` |

3. 点「测试连接」验证（成功显示 Model 与耗时；失败显示原因，不显示 Key）；
4. 保存后即可使用。也可以在项目根目录创建 `.env`（参考 `.env.example`），读取优先级为：环境变量 > 凭据管理器 > 本地配置。

## 使用流程

1. 打开聊天软件（微信 / QQ / Discord / Telegram / 浏览器均可）；
2. 点击「选择区域」或按 `Ctrl+Shift+S`；
3. 拖动框选**当前聊天区域**，`Enter` 确认（`Esc` 取消）；
4. 程序开始监控：OCR 每约 2 秒采样一次；
5. 对方发来新消息 → 「检测到新内容」→「等待文本稳定」→「AI 分析中」→ 自动更新分析；
6. 回复建议每条可一键「复制」，粘贴到聊天框发送。

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Shift+S` | 重新选择聊天区域 |

> 注：该快捷键是应用级快捷键（程序窗口有焦点时生效）。系统级全局热键不在 V1 范围。

## 实时机制说明

「实时」不等于每帧调用模型：

- OCR 采样默认 2000ms（可调 500–3000ms）；
- 检测到文本变化后先防抖 700ms（可调 300–1500ms），等待消息稳定；
- OCR 采用 **latest-only**：当前任务 + 最多一个最新待处理帧，绝不无限排队；
- LLM **最多 1 个在途请求**：新文本到达时旧请求结果被标记 stale，按 generation 丢弃，旧结果绝不会覆盖新结果；
- 相同的文本指纹**绝不重复调用** LLM（含滚动回来的情况）；
- 纯滚动（无新消息）只更新上下文显示，不触发 LLM；
- 旧分析结果在新结果就绪前**保持显示**，不出现白屏跳动。

## 隐私说明

- 截图**只存在内存中**，OCR 完成后即释放，不保存为图片、不写磁盘；
- OCR **全部在本地**执行（PaddleOCR），不上传截图；
- 发送给 LLM 的只有：**OCR 文本 + 必要上下文 + 系统 Prompt**（默认不发送截图）；
- 只截取用户**明确框选**的区域；不会后台扫描整个屏幕，不读取微信/QQ 等应用内部数据；
- API Key 存于 Windows 凭据管理器，**不硬编码、不进 Git、不写日志**；
- 日志位于 `%APPDATA%\OCRChatAssistant\logs\`，不记录 API Key 与完整聊天内容；
- 回复建议**只复制到剪贴板**，程序不会自动粘贴或发送任何消息。

## 已知限制

- Speaker 标签（对方/我）基于气泡左右位置的**启发式**，可能不准，不确定时显示「未知」；分析 Prompt 中已声明该标签仅供参考；
- 消息边界识别为 V1 级启发式（垂直间距 + 水平重叠），不保证 100% 准确；
- 多显示器 DPI 缩放按统一缩放比例换算（常见 Windows 场景已验证）；
- `Ctrl+Shift+S` 为应用内快捷键，聊天窗口在前台时需先激活本程序；
- OCR 对小字体、深色模式、表情气泡的识别效果取决于 PaddleOCR 模型，可能需要调整所选区域；
- 首次启动需下载 OCR 模型（PP-OCRv6，约 100MB），加载期间状态栏显示「正在加载 OCR 模型…」；
- 兼容性补丁（已内置在代码中，无需用户处理）：① six 1.17 的 `_SixMetaPathImporter` 与 Python 3.12 的 `importlib` repr 机制冲突，在 OCR 引擎初始化前自动修补；② paddlepaddle 3.3.1 的 OneDNN 与 PIR 执行器对 PP-OCRv6 有转换 bug，OCR 引擎已固定 `enable_mkldnn=False`（纯 CPU 模式，稳定但稍慢）。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

覆盖：配置加载（.env/缺失项/钳制）、文本标准化、变化检测（噪声/滚动/去重）、上下文管理（合并/去重/限制/清空）、Schema 校验、LLM 解析（fence/非法 JSON/缺字段）、Analyzer（Mock/错误/prompt 格式）、Scheduler（防抖/generation 陈旧丢弃/暂停恢复/清空/短文本）、PaddleOCR smoke（生成图片识别）、GUI 冒烟（主窗口/设置/选择器可实例化）、**E2E Mock 全链路**（假截图→假 OCR→变化→上下文→Mock LLM→UI 更新）。

全部测试**无需真实 API Key**。

## 开发说明

- 业务代码只依赖 `LLMClient` / `OCREngine` 接口，替换 Provider 或 OCR 引擎不需要改动 Context / Analyzer / GUI；
- 新增 Provider：实现 `LLMClient` 协议即可；
- GUI 主线程禁止执行 PaddleOCR 与 HTTP 请求，一律走 worker 线程 + Qt Signal；
- 修改 `app/llm/prompt.py` 可调整分析风格（System Prompt 含「不读心」原则，请勿移除）。

## Roadmap

- **V1.1**：更好的消息分段、Speaker 启发式增强、复制优化、Prompt/回复风格自定义
- **V1.2**：图片消息辅助理解、OCR 后处理增强、本地模型支持
- **V2**：Android（Accessibility Service 优先，MediaProjection 备选）
- **V3**：iOS（截图 + Vision/OCR + Share Extension）
