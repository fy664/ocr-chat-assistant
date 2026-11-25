> **历史规格**。本文描述 V1 实时监控方案。当前功能与结构见 [README](README.md) 和 [项目骨架](docs/ARCHITECTURE.md)。

# OCR Chat Assistant
## Windows 实时聊天语义分析助手 V1.0
### Claude Code 一次性实施规格 / Product Specification / Engineering Contract

> **用途**
>
> 本文档直接交给 Claude Code 执行。
> Claude Code 应把本文档视为本项目的最终产品规格、技术规格、开发顺序和验收标准。
>
> **目标**
>
> 从空项目开始，自动完成环境准备、依赖安装、项目搭建、代码实现、测试、启动、问题修复和最终验收。
> 不要只输出代码示例；必须真正修改当前工作区并运行验证。
>
> **本版本范围**
>
> 只实现 **Windows Desktop V1**。
> Android / iOS 不参与本轮开发，统一放到 V2 Roadmap。
>
> **核心体验**
>
> 用户第一次框选聊天区域后，程序持续观察这个区域：
>
> `框选聊天区域 → 持续截图 → 本地 OCR → 文本变化检测 → 上下文重建 → 自动触发 LLM → 实时更新语义分析与回复建议`
>
> 注意：
>
> “实时”不是每一帧调用模型，而是 **聊天内容发生有效变化后，经过短暂防抖，再自动分析最新上下文**。

---

# 1. 产品定义

## 1.1 产品名称

暂定：

**OCR Chat Assistant**

中文可显示：

**聊天语义助手**

---

## 1.2 产品目标

开发一个 Windows 桌面 AI 辅助工具，帮助用户理解当前屏幕中聊天对象表达的内容，并根据可见聊天上下文生成自然的回复建议。

程序不需要读取微信、QQ、Discord、Telegram、浏览器等应用的内部数据。

V1 只依赖：

- 用户主动选择的屏幕区域
- 用户主动启动的监控
- 本地 OCR
- 用户主动配置的第三方 LLM API

---

# 2. 核心用户体验

目标体验必须接近下面的流程：

```text
用户打开聊天软件
        ↓
启动 OCR Chat Assistant
        ↓
按快捷键进入区域选择
        ↓
拖动鼠标框选“当前聊天区域”
        ↓
点击确认
        ↓
程序开始持续监控该区域
        ↓
PaddleOCR 本地识别文字
        ↓
检测聊天内容是否发生有效变化
        ↓
发生变化
        ↓
短暂 debounce，等待对方消息稳定
        ↓
更新 Conversation Context
        ↓
自动调用用户配置的 LLM
        ↓
解析结构化结果
        ↓
实时更新悬浮分析面板
        ↓
显示：
  - 当前表层意思
  - 可能意图
  - 情绪
  - 潜在诉求
  - 回复策略
  - 2~3 条回复建议
```

用户不需要每次手动复制文本。

用户也不需要每条新消息点击“分析”。

---

# 3. V1 与 V2 边界

## 3.1 V1 必须实现

### 输入

- 手动框选屏幕区域
- 固定聊天区域持续截图
- 本地 OCR
- OCR 文本变化检测
- OCR 文本编辑
- 上下文管理

### AI

- OpenAI-compatible API
- 用户自行选择模型厂商
- 用户自行输入 API Key
- Base URL 可配置
- Model 可配置
- 结构化输出
- 意图分析
- 情绪分析
- 潜在诉求分析
- 回复策略
- 推荐回复

### 实时

- 自动监控选定区域
- 有效文本变化检测
- debounce
- 取消过期请求/忽略过期结果
- 新结果自动覆盖旧结果
- GUI 不阻塞
- 分析过程中显示状态

### 桌面端

- Windows
- PySide6
- 悬浮窗口
- 置顶
- 可移动
- 可调整大小
- 快捷键
- 设置页面
- 暂停 / 恢复
- 重新选择区域

---

## 3.2 V1 明确不实现

禁止在本轮开发：

- Android
- iOS
- Accessibility Service
- Windows 无障碍自动读取第三方应用控件
- 自动读取微信/QQ内部数据
- 后台隐藏监听第三方应用
- 自动点击第三方应用
- 自动发送消息
- 自动替用户回复
- 自动修改第三方聊天软件内容
- 云端 OCR
- 自建后端
- 用户账号
- SaaS
- 数据库服务器
- 支付
- 自动收集用户聊天数据
- 聊天内容上传到项目作者自己的服务器
- 训练数据采集
- MCP
- 多 Agent
- 复杂 Tool Calling
- Redis / Kafka / Docker / Kubernetes
- 不必要的 Web 服务

---

# 4. Android V2 说明

Android 单独作为下一阶段。

V2 再研究：

```text
Accessibility Service
        ↓
优先获取聊天 App 可访问文本
        ↓
Context
        ↓
LLM
```

读取不到文本时，再考虑：

```text
MediaProjection
        ↓
用户主动授权
        ↓
截图
        ↓
OCR
```

V1 绝对不要因为“未来要做 Android”而在 Windows 版本提前实现 Android 权限、无障碍或跨平台复杂抽象。

---

# 5. 隐私与安全设计

## 5.1 基本原则

程序采用：

```text
用户主动触发
+
用户主动选择
+
本地 OCR
+
用户主动确认进入 AI 分析
```

程序不得默认：

```text
后台持续扫描整个屏幕
+
偷偷读取其他窗口
+
自动向远程服务器发送截图
```

---

## 5.2 截图数据

截图：

- 只存在内存中
- 默认不写磁盘
- OCR 完成后及时释放
- 不保存为历史图片
- 不上传到项目自己的服务器

程序只截取用户明确选择的区域。

---

## 5.3 发送给 LLM 的内容

默认只发送：

```text
OCR 后的文字
+
必要的上下文
+
系统 Prompt
```

默认不向 LLM 发送截图图片。

---

## 5.4 API Key

绝对禁止：

```python
API_KEY = "sk-xxxx"
```

禁止：

- 硬编码
- 写进 Git
- 写入日志
- 出现在异常堆栈
- 在 UI 日志区展示

开发环境至少支持 `.env`。

如果实现 Windows 凭据存储不显著增加复杂度，优先使用 Windows Credential Manager / keyring 存储 API Key。

---

# 6. 技术栈

## 6.1 Python

优先：

```text
Python 3.11
```

允许：

```text
Python 3.12
```

但 Claude Code 必须先检查实际 Python 环境。

如果当前 Python 版本与 PaddlePaddle / PaddleOCR 当前兼容环境冲突：

1. 不要强行破坏系统 Python；
2. 创建项目专用虚拟环境；
3. 必要时使用 Python 3.11；
4. 记录最终可用版本；
5. 把实际验证过的版本写入文档。

---

## 6.2 GUI

```text
PySide6
```

理由：

- Windows 桌面支持良好
- Qt 窗口系统成熟
- 悬浮窗、快捷键、线程和绘制能力完整

---

## 6.3 屏幕截图

```text
mss
```

要求：

- 支持多显示器
- 获取屏幕像素
- 截取用户指定区域
- 不落盘

---

## 6.4 OCR

```text
PaddleOCR
```

使用当前稳定版本。

不要盲目锁死过时版本。

Claude Code 必须：

1. 根据当前 Python 环境选择可用 PaddlePaddle；
2. 安装 PaddleOCR；
3. 实际执行 import；
4. 运行 OCR smoke test；
5. 只有通过验证后才算 OCR 环境完成。

PaddleOCR 的依赖与安装方式可能随版本和设备变化，因此不要假设一套旧版命令永久有效；应根据当前环境实际安装、验证并记录可工作的版本组合。

---

## 6.5 LLM

使用：

```text
OpenAI-compatible API
```

核心依赖可以使用：

```text
openai
```

通过：

```text
api_key
base_url
model
```

完成统一接入。

本项目优先采用各家 OpenAI-compatible Provider 都较容易适配的统一调用路径，不依赖某一家厂商的专属能力；具体 SDK 调用方式以实际 Provider 的兼容性验证结果为准。

---

## 6.6 数据模型

```text
Pydantic
```

所有 AI 输出必须经过 Schema 验证。

---

## 6.7 配置

```text
python-dotenv
```

开发环境：

```text
.env
```

必须有：

```text
.env.example
```

---

## 6.8 测试

```text
pytest
```

---

# 7. 推荐项目结构

```text
ocr-chat-assistant/
│
├─ app/
│  ├─ __init__.py
│  ├─ main.py
│  │
│  ├─ config/
│  │  ├─ __init__.py
│  │  └─ settings.py
│  │
│  ├─ capture/
│  │  ├─ __init__.py
│  │  ├─ screen_capture.py
│  │  ├─ region_selector.py
│  │  └─ monitor.py
│  │
│  ├─ ocr/
│  │  ├─ __init__.py
│  │  ├─ engine.py
│  │  ├─ preprocess.py
│  │  ├─ normalize.py
│  │  └─ diff.py
│  │
│  ├─ context/
│  │  ├─ __init__.py
│  │  ├─ models.py
│  │  ├─ manager.py
│  │  └─ builder.py
│  │
│  ├─ llm/
│  │  ├─ __init__.py
│  │  ├─ client.py
│  │  ├─ provider.py
│  │  ├─ prompt.py
│  │  └─ parser.py
│  │
│  ├─ analysis/
│  │  ├─ __init__.py
│  │  ├─ analyzer.py
│  │  └─ scheduler.py
│  │
│  ├─ models/
│  │  ├─ __init__.py
│  │  └─ schemas.py
│  │
│  ├─ ui/
│  │  ├─ __init__.py
│  │  ├─ main_window.py
│  │  ├─ floating_panel.py
│  │  ├─ settings_dialog.py
│  │  ├─ ocr_editor.py
│  │  ├─ status_bar.py
│  │  └─ styles.py
│  │
│  └─ utils/
│     ├─ __init__.py
│     ├─ logger.py
│     └─ time.py
│
├─ tests/
│  ├─ test_config.py
│  ├─ test_diff.py
│  ├─ test_context.py
│  ├─ test_schema.py
│  ├─ test_parser.py
│  ├─ test_analyzer.py
│  └─ test_smoke.py
│
├─ assets/
│
├─ .env.example
├─ .gitignore
├─ requirements.txt
├─ README.md
├─ PROJECT_SPEC.md
├─ run.py
├─ setup.ps1
└─ run.ps1
```

可以根据实现需要调整文件，但职责必须保持分离。

---

# 8. 总体架构

```text
┌──────────────────────────────────────────────┐
│                  PySide6 UI                  │
│                                              │
│  状态 / OCR / 分析 / 回复建议 / 设置         │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│            Region Monitor / Capture          │
│                                              │
│  固定区域截图                                 │
│  定时采样                                     │
│  latest-only                                  │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│                  OCR Layer                   │
│                                              │
│  preprocess                                  │
│      ↓                                       │
│  PaddleOCR                                   │
│      ↓                                       │
│  normalize                                    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│               Change Detection               │
│                                              │
│  当前文本 fingerprint                         │
│  vs                                           │
│  上一次稳定文本 fingerprint                   │
└──────────────────────┬───────────────────────┘
                       │
                无变化 │       有变化
                       │          │
                       │          ▼
                       │     debounce
                       │          │
                       │          ▼
                       │   Context Builder
                       │          │
                       │          ▼
                       │      LLM Analyzer
                       │          │
                       │          ▼
                       │   Pydantic Validator
                       │          │
                       │          ▼
                       └──────→ UI Update
```

---

# 9. 实时机制——本项目最关键部分

## 9.1 不允许的实现

禁止：

```text
每一帧截图
    ↓
每一帧 OCR
    ↓
每一帧调用 LLM
```

这会导致：

- API 成本爆炸
- 模型重复分析
- UI 抖动
- 请求堆积
- 上下文混乱
- CPU 占用过高

---

# 10. 正确的实时 Pipeline

采用：

```text
Timer
 ↓
Capture selected region
 ↓
Preprocess
 ↓
OCR
 ↓
Normalize text
 ↓
Compare fingerprint
 ↓
No change → discard
 ↓
Changed
 ↓
Debounce
 ↓
Create analysis request
 ↓
LLM
 ↓
Update UI
```

---

# 11. OCR 采样

默认：

```text
capture_interval = 1000 ms
```

允许用户设置：

```text
500 ms ~ 3000 ms
```

推荐默认：

```text
1000 ms
```

原因：

实时感和 CPU 占用需要平衡。

---

# 12. latest-only 原则

如果 OCR 正在处理上一张截图，新截图继续产生：

不要建立无限队列。

采用：

```text
当前 OCR 任务
+
最多一个最新待处理帧
```

即：

```text
Frame A → OCR processing

期间产生：
Frame B
Frame C
Frame D

不要排队 A/B/C/D。

只保留：
D
```

OCR 完成后直接处理 D。

---

# 13. 文本变化检测

OCR 输出必须进行 normalized text。

例如：

```text
原始：
你 好   吗


标准化：
你 好 吗
```

计算：

```text
fingerprint(normalized_text)
```

如果：

```text
new_fingerprint == last_fingerprint
```

不触发 LLM。

---

# 14. OCR 噪声过滤

不能因为一个标点变化就触发 LLM。

例如：

```text
你好！
```

OCR 下一次：

```text
你好 ！
```

不应被视为真正的新消息。

因此必须进行：

- whitespace normalization
- repeated punctuation normalization
- obvious OCR noise cleanup

但不要过度修改原始文本。

---

# 15. Debounce

默认：

```text
700 ms
```

可配置：

```text
300 ms ~ 1500 ms
```

逻辑：

```text
检测到变化
    ↓
等待 700ms
    ↓
如果期间没有再次变化
    ↓
触发 AI
```

例如对方连续发送：

```text
你周末有空吗
```

随后：

```text
怎么不回我
```

最后：

```text
是不是不想出来
```

程序不应立即发起三次模型请求。

应等待文本稳定后分析最新上下文。

---

# 16. LLM 请求防重复

每次分析请求必须有：

```text
request_id
```

同时保存：

```text
analysis_generation
```

示例：

```text
Generation 10 → 请求 A
Generation 11 → 请求 B
```

如果 A 比 B 晚返回：

```text
禁止 A 覆盖 B
```

UI 只接受：

```text
最新 generation 的结果
```

---

# 17. LLM 请求并发控制

默认：

```text
max_active_analysis = 1
```

不要让多个分析请求同时消耗 API。

当新文本出现：

```text
旧请求：
    如果客户端支持取消 → 尝试取消

否则：
    标记旧请求结果为 stale

新请求：
    generation + 1
    发送
```

---

# 18. 实时性的定义

V1 的“实时”定义：

> 当选定聊天区域中的可识别文本发生稳定变化后，程序应自动触发新的分析，并在正常网络和模型响应条件下尽快更新结果。

不要承诺：

```text
毫秒级
零延迟
100% 每条消息立即识别
```

---

# 19. 上下文设计

## 19.1 当前可见聊天文本

OCR 每次获得的是：

```text
当前屏幕选定区域中的完整可见文本
```

Context Manager 维护一个：

```text
rolling context
```

---

## 19.2 Context 不应该无限增长

默认：

```text
max_messages = 20
```

或：

```text
max_chars = 8000
```

最终限制以 token / 字符数 whichever comes first。

---

# 20. Context 更新原则

OCR 每次产生的是“当前屏幕快照”。

Context 层不要简单粗暴：

```text
每次 snapshot 都 append
```

否则：

```text
A
A
A
A
B
B
C
```

会产生大量重复。

应根据 normalized text + message segmentation heuristic 做增量合并。

---

# 21. V1 允许的上下文模型

V1 不要求 100% 准确识别聊天消息边界。

优先保证：

```text
最新可见聊天文本
+
少量历史上下文
```

可靠性优先于过度复杂的 OCR 聊天气泡解析。

---

# 22. Speaker 识别

OCR 本身不能可靠知道：

```text
这是谁说的
```

因此 V1：

- 保留 OCR 行的 bounding box；
- 如果可以通过左右位置推测 speaker，可以作为 heuristic；
- speaker 不确定时必须设为 `unknown`；
- 不允许把 heuristic 当成事实。

建议模型输入格式：

```text
[对话内容]
对方/我/未知：……
```

speaker 不确定时：

```text
未知：……
```

---

# 23. OCR 编辑

必须允许用户手动修正识别内容。

界面必须提供：

```text
原始 OCR
```

和：

```text
当前分析文本
```

用户可以：

- 修改
- 删除
- 添加
- 复制

修改后的文本优先进入分析。

---

# 24. 手动重选区域

提供按钮：

```text
重新选择区域
```

快捷键默认：

```text
Ctrl + Shift + S
```

执行：

```text
Pause monitor
    ↓
进入全屏半透明选择器
    ↓
用户拖动框选
    ↓
Confirm
    ↓
保存新的 region
    ↓
Reset OCR state
    ↓
Resume monitor
```

---

# 25. 暂停 / 恢复

主界面必须有：

```text
暂停监控
```

暂停时：

- 不截图
- 不 OCR
- 不触发 LLM

恢复时：

- 获取一张新的基准截图
- 不立即把旧文本重复提交
- 从新快照开始计算变化

---

# 26. GUI 设计

整体风格：

- 简洁
- 小型
- 桌面工具
- 信息密度适中
- 可长时间悬浮

---

# 27. 主窗口

建议：

```text
┌──────────────────────────────────────┐
│ OCR Chat Assistant             ⚙  × │
├──────────────────────────────────────┤
│                                      │
│  监控区域：已选择                     │
│  状态：正在监控                       │
│                                      │
│  当前聊天                             │
│  ┌──────────────────────────────────┐ │
│  │ 对方：你周末有空吗？             │ │
│  │ 我：应该有吧                     │ │
│  │ 对方：怎么不回我                 │ │
│  └──────────────────────────────────┘ │
│                                      │
│  AI 分析                              │
│  ┌──────────────────────────────────┐ │
│  │ 表层意思                         │ │
│  │ ……                               │ │
│  │                                  │ │
│  │ 可能意图                         │ │
│  │ ……                               │ │
│  │                                  │ │
│  │ 情绪                             │ │
│  │ ……                               │ │
│  │                                  │ │
│  │ 潜在诉求                         │ │
│  │ ……                               │ │
│  │                                  │ │
│  │ 回复策略                         │ │
│  │ ……                               │ │
│  └──────────────────────────────────┘ │
│                                      │
│  回复建议                             │
│  ┌──────────────────────────────────┐ │
│  │ 自然：……                  [复制] │ │
│  │ 温和：……                  [复制] │ │
│  │ 简短：……                  [复制] │ │
│  └──────────────────────────────────┘ │
│                                      │
│ [选区域] [暂停] [清空] [设置]        │
└──────────────────────────────────────┘
```

---

# 28. 悬浮窗

窗口支持：

```text
Qt.WindowStaysOnTopHint
```

要求：

- always on top
- 可以拖动
- 可以调整大小
- 不遮挡用户选择区域太多
- 方便放在微信/QQ旁边

---

# 29. 状态栏

至少显示：

```text
未开始
选择区域中
监控中
OCR 中
等待文本稳定
AI 分析中
分析完成
暂停
错误
```

---

# 30. 分析结果展示

建议按卡片展示：

```text
当前理解
可能意图
情绪
潜在诉求
建议策略
回复建议
不确定性
```

不要求每次都全部刷新视觉动画。

应采用稳定 UI 更新，避免内容跳动。

---

# 31. AI 输出模型

使用 Pydantic。

建议 Schema：

```python
class EmotionResult(BaseModel):
    label: str
    confidence: float | None = None
    evidence: str | None = None


class SuggestedReply(BaseModel):
    style: str
    text: str


class AnalysisResult(BaseModel):
    surface_meaning: str
    possible_intent: list[str]
    emotion: EmotionResult
    potential_needs: list[str]
    reply_strategy: str
    suggested_replies: list[SuggestedReply]
    uncertainty: str
```

允许根据实际开发优化类型，但必须保持核心字段。

---

# 32. AI 最重要的原则：不能“读心”

System Prompt 必须强调：

```text
你不是读心工具。

你不能声称知道聊天对象真实心理。

请区分：
1. 对方明确说了什么；
2. 基于文本和上下文做出的合理推测；
3. 当前信息无法判断的内容。

不要把可能性写成确定事实。
```

例如：

错误：

```text
她就是生气了。
```

正确：

```text
当前文本可能体现出不满，但仅凭现有上下文无法确定真实情绪。
```

---

# 33. System Prompt

实现为独立 Prompt。

建议初始 Prompt：

```text
你是一名聊天语义分析助手。

你的任务是分析用户提供的聊天上下文，帮助用户理解对方当前表达，并提供自然的回复建议。

你需要输出：

1. 当前消息的表层意思；
2. 对方可能的意图；
3. 对方可能呈现出的情绪；
4. 对方可能的潜在诉求；
5. 合理的回复策略；
6. 2~3 条自然的回复建议；
7. 对判断不确定性的说明。

重要规则：

- 不要声称可以读取或确定对方内心。
- 不要把推测当成事实。
- 信息不足时明确说明不确定性。
- 只能基于提供的聊天内容进行分析。
- 不要制造不存在的上下文。
- 不要加入用户没有提供的事实。
- 回复建议应该自然、简洁、符合聊天场景。
- 避免客服腔和机械模板。
- 回复建议只是候选，不代表唯一正确答案。
- 保留沟通中的不确定性。
- 输出必须符合指定 JSON Schema。
```

---

# 34. Prompt 输入格式

推荐：

```text
【聊天上下文】

对方：这周末有空吗？
我：应该有吧
对方：怎么不回我？
对方：是不是不想出来？

【当前状态】

请分析当前最新聊天内容。
```

无上下文时：

```text
【聊天上下文】

无可用历史上下文。

【当前状态】

对方：……
```

---

# 35. 回复建议

固定提供 2~3 条。

默认风格：

```text
自然
温和
简短
```

示例数据结构：

```json
{
  "style": "自然",
  "text": "..."
}
```

不要生成：

- 极端操控性话术
- 欺骗性承诺
- 虚构事实
- 明显模板化客服文案

---

# 36. LLM Provider 架构

不要写死：

```python
DeepSeekClient
```

业务代码只认识：

```python
LLMClient
```

建议：

```python
class LLMClient(Protocol):
    def analyze(
        self,
        system_prompt: str,
        context: str
    ) -> AnalysisResult:
        ...
```

实际可以：

```text
OpenAICompatibleClient
```

配置：

```text
provider_name
api_key
base_url
model
temperature
timeout
```

---

# 37. Provider UI

设置页至少有：

```text
Provider 名称
API Key
Base URL
Model
Temperature
Timeout
```

例如：

```text
Provider:
[ 自定义 ]

API Key:
[ *************** ]

Base URL:
[ https://example.com/v1 ]

Model:
[ model-name ]

Temperature:
[ 0.3 ]

Timeout:
[ 30 ]

[测试连接]
[保存]
```

---

# 38. Provider 设计原则

用户可以：

```text
切换厂商
```

而无需修改 Python 代码。

例如可以配置：

```text
OpenAI-compatible provider A
OpenAI-compatible provider B
OpenAI-compatible provider C
本地 OpenAI-compatible server
```

项目本身不依赖具体厂商。

---

# 39. API Key 配置方式

支持：

```env
LLM_PROVIDER=
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TEMPERATURE=0.3
LLM_TIMEOUT=90
```

`.env.example`：

```env
LLM_PROVIDER=custom
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TEMPERATURE=0.3
LLM_TIMEOUT=90
```

`.gitignore` 必须包含：

```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

---

# 40. 测试连接

设置页提供：

```text
测试连接
```

测试内容：

- API Key 是否存在
- Base URL 是否有效
- Model 是否存在
- Provider 是否能返回结果
- 请求耗时

成功：

```text
连接成功
Model: xxx
Latency: xxx ms
```

失败：

```text
连接失败
原因：HTTP 401 / 404 / timeout / network error / invalid response
```

不要显示 API Key。

---

# 41. LLM 结构化解析

处理流程：

```text
LLM response
    ↓
extract content
    ↓
JSON parse
    ↓
Pydantic validation
    ↓
AnalysisResult
```

不能只：

```python
json.loads(...)
```

而不验证。

---

# 42. JSON 失败处理

如果模型没有返回合法 JSON：

### 第一次

尝试：

```text
解析
```

失败后：

```text
结构化修复 / retry
```

### 第二次仍失败

显示：

```text
AI 返回格式异常，请重新分析。
```

记录安全日志，但：

- 不记录 API Key
- 默认不记录完整聊天内容

---

# 43. LLM 错误处理

必须处理：

```text
401
403
404
429
500
502
503
timeout
network error
invalid JSON
empty response
```

用户可读提示：

```text
API Key 无效
模型不存在
请求频率过高
服务暂时不可用
网络请求超时
AI 返回格式异常
```

---

# 44. GUI 线程模型

绝对禁止：

```text
在 GUI 主线程直接执行：
PaddleOCR
HTTP request
```

否则窗口容易卡死。

使用：

```text
QThread
QThreadPool
QRunnable
```

或等效 Qt Worker 架构。

推荐：

```text
GUI Thread
    │
    ├── Screenshot
    │
    ├── Render
    │
    └── WorkerPool
          ├── OCR worker
          └── LLM worker
```

---

# 45. Worker 通信

Worker 不直接操作 UI。

采用：

```text
Worker
 ↓
Qt Signal
 ↓
Main Window
```

例如：

```text
ocr_started
ocr_completed
text_changed
analysis_started
analysis_completed
analysis_failed
```

---

# 46. 状态机

应用至少支持：

```text
IDLE
SELECTING_REGION
MONITORING
OCR_PROCESSING
WAITING_DEBOUNCE
ANALYZING
SHOWING_RESULT
PAUSED
ERROR
```

---

# 47. Region Monitor

设计：

```python
RegionMonitor(
    region,
    interval_ms=1000
)
```

产生：

```text
ScreenshotFrame
```

其中：

```text
x
y
width
height
timestamp
image
```

---

# 48. 区域选择器

使用 PySide6 overlay：

```text
全屏覆盖
+
半透明遮罩
+
鼠标拖动矩形
+
实时显示宽高
+
Enter 确认
+
Esc 取消
```

选择结果：

```python
ScreenRegion(
    x=...,
    y=...,
    width=...,
    height=...
)
```

必须考虑：

- 多显示器
- DPI scaling
- 缩放比例
- 负坐标显示器

至少完成常见 Windows 单屏场景，并为多显示器保留正确坐标模型。

---

# 49. OCR Engine

接口：

```python
class OCREngine:
    def recognize(image) -> OCRResult:
        ...
```

OCRResult 至少包括：

```text
raw_text
lines
confidence
boxes
```

---

# 50. OCR 预处理

建议：

```text
截图
 ↓
RGB conversion
 ↓
resize
 ↓
contrast normalization
 ↓
可选 grayscale
 ↓
OCR
```

不要一开始做复杂图像算法。

通过真实聊天截图测试后，再针对：

- 小字体
- 深色模式
- 浅色模式
- 气泡背景
- 多行消息

做必要调整。

---

# 51. OCR 速度优化

优先：

```text
只截取用户选择区域
```

不要：

```text
每次 OCR 全屏
```

同时：

```text
latest-only queue
```

防止积压。

---

# 52. OCR 失败

如果：

```text
没有有效文本
```

状态：

```text
未识别到文字
```

不要触发 LLM。

如果 OCR 文本太短：

```text
例如少于 2~3 个有效字符
```

可以只更新显示，不触发 AI。

阈值应可配置。

---

# 53. Context Manager

接口：

```python
add_snapshot(text)
get_context()
clear()
```

必须去重。

必须限制长度。

必须保证：

```text
最新内容
```

拥有最高优先级。

---

# 54. Context 建议结构

```python
class ContextMessage:
    content: str
    speaker: str | None
    timestamp: float
```

上下文：

```python
class ConversationContext:
    messages: list[ContextMessage]
```

---

# 55. 上下文滚动策略

默认：

```text
最多 20 条消息
```

和：

```text
最多 8000 字符
```

同时存在时取较严格限制。

---

# 56. “实时”UI 行为

例如聊天发生变化：

```text
状态：检测到新内容
```

然后：

```text
状态：分析中...
```

然后：

```text
状态：分析完成
```

如果短时间连续发生变化：

```text
状态：等待文本稳定...
```

不要不断弹窗。

---

# 57. 分析结果更新策略

旧结果：

```text
保留
```

直到新结果准备好。

避免：

```text
消息变化
→ 整个界面清空
→ 长时间白屏
```

正确：

```text
旧结果继续显示
+
右上角状态：
“正在更新分析…”
```

新结果完成后：

```text
原子替换
```

---

# 58. 复制回复

每条回复后提供：

```text
复制
```

点击：

```text
复制到系统剪贴板
```

注意：

**V1 只复制到剪贴板，不自动粘贴，不自动发送。**

---

# 59. 清空

提供：

```text
清空上下文
```

操作：

```text
Context = empty
AnalysisResult = empty
OCR baseline = current snapshot
```

避免清空后下一次 OCR 把旧聊天重新全部当作新内容。

---

# 60. 设置页

设置分为：

### LLM

```text
Provider
API Key
Base URL
Model
Temperature
Timeout
```

### Realtime

```text
OCR Interval
Debounce
Max Context
```

默认：

```text
OCR Interval = 1000ms
Debounce = 700ms
Max Context Messages = 20
Max Context Characters = 8000
```

### UI

```text
始终置顶
启动时是否自动进入监控
```

默认：

```text
始终置顶 = true
启动自动监控 = false
```

---

# 61. 配置存储

普通配置：

```text
%APPDATA%\OCRChatAssistant\config.json
```

敏感信息：

```text
优先 Windows Credential Manager / keyring
```

开发阶段允许：

```text
.env
```

读取优先级建议：

```text
环境变量 / keyring
    >
本地配置
```

不得把 API Key 输出到日志。

---

# 62. 日志

使用：

```python
logging
```

日志文件：

```text
%APPDATA%\OCRChatAssistant\logs\
```

建议：

```text
app.log
```

记录：

```text
application startup
configuration loaded
region selected
OCR started/completed
text changed
analysis started/completed
request latency
errors
```

禁止记录：

```text
API Key
完整敏感聊天内容
截图二进制
```

---

# 63. 性能要求

V1 不追求极致性能，但必须避免明显卡顿。

目标：

```text
GUI 主线程不卡死
OCR 不无限堆积
LLM 不无限并发
无变化时不调用 LLM
```

推荐策略：

```text
Screenshot sampling: 1000ms
Debounce: 700ms
Max active LLM: 1
OCR queue: latest-only
```

---

# 64. 网络策略

LLM：

```text
timeout = 90s
```

可配置。

建议：

```text
max retries = 1
```

仅针对：

- transient network error
- 5xx

不要对：

```text
401
403
404
```

反复重试。

---

# 65. Token / 成本控制

每次请求尽量只发送：

```text
最新上下文
+
必要 Prompt
```

不要把无关系统信息发送给模型。

不要在没有文本变化时发送请求。

默认：

```text
temperature = 0.3
```

主要目标是：

```text
稳定
自然
低随机性
```

---

# 66. 应用启动流程

```text
python run.py
      ↓
加载 Config
      ↓
初始化 Logger
      ↓
初始化 Qt Application
      ↓
初始化 OCR Engine
      ↓
初始化 LLM Client
      ↓
显示 Main Window
```

注意：

PaddleOCR 模型初始化可能较慢。

不能因为 OCR 初始化慢而让 GUI 长时间完全无响应。

可采用启动 Worker：

```text
GUI 先打开
       ↓
OCR 初始化后台进行
       ↓
状态：
“正在加载 OCR 模型…”
       ↓
完成
       ↓
状态：
“就绪”
```

---

# 67. 首次启动

首次运行：

```text
没有 API Key
```

允许正常启动。

UI 提示：

```text
请在设置中配置 LLM。
```

不要因此整个程序无法启动。

---

# 68. 无 API Key 时

必须仍然支持：

```text
截图
OCR
OCR 文本编辑
```

只有：

```text
AI 分析
```

提示：

```text
请先配置 LLM API Key。
```

这样用户可以单独验证 OCR。

---

# 69. Mock LLM

测试必须支持：

```text
MockLLMClient
```

无需真实 API Key。

Mock 返回固定合法：

```json
{
  "surface_meaning": "测试消息",
  "possible_intent": ["测试意图"],
  "emotion": {
    "label": "中性",
    "confidence": 1.0,
    "evidence": "测试"
  },
  "potential_needs": ["测试需求"],
  "reply_strategy": "测试策略",
  "suggested_replies": [
    {
      "style": "自然",
      "text": "测试回复"
    },
    {
      "style": "温和",
      "text": "测试回复"
    },
    {
      "style": "简短",
      "text": "好的"
    }
  ],
  "uncertainty": "这是测试数据"
}
```

---

# 70. 测试要求

运行：

```powershell
pytest -q
```

必须在：

```text
没有真实 API Key
```

的情况下通过绝大多数自动测试。

---

# 71. 单元测试

至少测试：

## Config

- 默认配置
- `.env`
- 缺失 Key
- 缺失 Model
- 缺失 Base URL

## Text Normalize

- 空格
- 换行
- 重复标点
- 空字符串

## Diff

- 相同文本
- 不同文本
- 微小 OCR 噪声
- 真正新增消息

## Context

- 添加
- 去重
- 长度限制
- 清空

## Schema

- 合法数据
- 缺字段
- 错误类型
- 非法 confidence

## LLM Parser

- 合法 JSON
- Markdown code fence JSON
- 非法 JSON
- 缺失字段

## Analyzer

- Mock LLM
- 正常分析
- LLM error
- stale generation

---

# 72. Smoke Test

建立：

```text
tests/assets/
```

测试图片可以由代码自动生成。

例如生成简单英文文字：

```text
Hello OCR 123
```

用于确认：

```text
PaddleOCR import
model load
recognition call
```

不依赖真实用户截图。

---

# 73. GUI Smoke Test

至少确认：

```text
Main Window can instantiate
Settings dialog can instantiate
Region selector can instantiate
No import error
```

不要求 CI 环境真正操作鼠标。

---

# 74. End-to-End Mock Test

必须实现：

```text
Fake screenshot
 ↓
Mock OCR
 ↓
Text changed
 ↓
Context
 ↓
Mock LLM
 ↓
AnalysisResult
 ↓
UI update
```

整个业务流程无需真实 API。

---

# 75. 真实 LLM 手动验收

如果用户已经填写 API Key：

Claude Code 应运行真实连接测试。

如果没有 API Key：

- 不要假装真实 LLM 已测试；
- 使用 Mock 完成自动测试；
- 明确告诉用户真实 API 仍需要配置。

---

# 76. 一键安装

创建：

```text
setup.ps1
```

完成：

```text
检查 Python
创建 .venv
升级 pip
安装 requirements
验证核心依赖
```

运行：

```powershell
.\setup.ps1
```

---

# 77. 一键运行

创建：

```text
run.ps1
```

行为：

```text
使用项目 .venv
启动 python run.py
```

用户最终可以：

```powershell
.\run.ps1
```

或者：

```powershell
python run.py
```

---

# 78. requirements.txt

至少包括实际使用到的：

```text
PySide6
mss
Pillow
numpy
pydantic
python-dotenv
openai
pytest
paddleocr
```

PaddlePaddle 不允许简单假定一个固定 GPU 包。

Claude Code 应：

1. 判断当前系统；
2. 选择 CPU / GPU；
3. 安装兼容版本；
4. 成功 import 后再锁定最终依赖版本。

如果最终需要独立安装 PaddlePaddle：

在 README 中明确安装顺序。

---

# 79. README

README 必须完整包含：

```text
项目简介
功能
技术架构
项目结构
环境要求
安装
运行
首次配置
LLM Provider 配置
截图操作
实时监控
快捷键
隐私说明
已知限制
测试
开发说明
Roadmap
```

---

# 80. README 中必须明确

### 数据流

```text
屏幕区域
 ↓
本地 OCR
 ↓
文本
 ↓
用户配置的 LLM API
 ↓
分析结果
```

明确：

```text
截图默认不保存
OCR 默认本地执行
不会自动读取第三方应用内部数据
不会自动发送消息
```

---

# 81. 可观测性

状态栏建议显示：

```text
OCR: Ready / Busy
LLM: Ready / Busy
Last update: HH:MM:SS
```

调试模式可以显示：

```text
OCR latency
LLM latency
Context size
```

但默认不要显示敏感聊天内容到日志。

---

# 82. 失败恢复

任何一个模块失败，整个应用不能崩溃。

例如：

```text
OCR error
```

应：

```text
显示错误
 ↓
继续监控
 ↓
下一次 frame 继续尝试
```

例如：

```text
LLM error
```

应：

```text
保留旧分析
显示请求失败
继续等待下一次有效文本变化
```

---

# 83. 避免重复分析

需要：

```text
stable_text_hash
```

以及：

```text
last_analyzed_hash
```

如果：

```text
current_hash == last_analyzed_hash
```

禁止再次调用 LLM。

---

# 84. 滚动场景

用户聊天窗口向上/向下滚动会导致 OCR 内容变化。

V1：

```text
允许把它视作当前可见上下文变化
```

但是要尽量避免：

```text
只是滚动相同内容
→ 大量重复 LLM 调用
```

因此可以比较：

```text
normalized visible text
```

只有文本集合明显变化时才触发分析。

---

# 85. OCR 与 LLM 解耦

必须保证未来可以：

```text
PaddleOCR
```

换成：

```text
其他 OCR
```

而不用改：

```text
Context
Analyzer
GUI
```

同理：

```text
LLM Provider
```

可以替换而不改 OCR。

---

# 86. 不要引入 Agent Framework

V1 不是复杂 Agent。

不要为了“AI Agent”而安装：

```text
LangChain
LangGraph
AutoGen
CrewAI
```

除非 Claude Code 在实现过程中发现有明确必要，并且必须说明理由。

V1 本质：

```text
Perception
→ Context
→ Reasoning
→ Presentation
```

---

# 87. 不需要 FastAPI

V1 是：

```text
Desktop App
```

不是：

```text
Web App
```

不要为了后端而强行引入：

```text
FastAPI
Uvicorn
```

LLM 可以直接从本机程序请求。

未来 Android V2 再根据需要决定：

```text
手机
 ↓
API
 ↓
后端
```

---

# 88. 未来扩展接口

代码结构需要方便以后增加：

```text
Android client
Browser extension
Image understanding
Voice
User reply draft
Local LLM
```

但 V1 不实现。

---

# 89. Android V2 Roadmap

未来：

```text
V2 Android
```

方向：

### 首选

```text
Accessibility Service
```

获取：

```text
可访问文本节点
```

### 备用

```text
MediaProjection
+
OCR
```

权限必须由用户主动授予。

V1 不实现任何 Android 代码。

---

# 90. iOS V3 Roadmap

未来可以考虑：

```text
Screenshot
+
Vision / OCR
+
Share Extension
```

V1 不实现。

---

# 91. 版本演进

## V1.0

```text
Windows
截图框选
固定区域监控
PaddleOCR
实时变化检测
Context
LLM
意图分析
情绪分析
回复建议
悬浮窗
```

## V1.1

```text
更好的消息分段
Speaker heuristic
复制优化
Prompt 自定义
回复风格自定义
```

## V1.2

```text
图片消息辅助理解
更好的 OCR 后处理
本地模型支持
```

## V2

```text
Android
Accessibility
```

---

# 92. 代码实现顺序

Claude Code 必须按以下顺序推进。

## Phase 0 — 项目检查

执行：

```powershell
Get-Location
Get-ChildItem
python --version
git --version
```

检查：

- Python
- Git
- 当前目录
- 是否已有项目文件
- 是否已有 venv

如果项目不是空的：

- 不直接覆盖；
- 先读取已有代码；
- 仅保留可复用内容；
- 不删除用户代码，除非确实属于本项目且需要重构。

---

## Phase 1 — 环境

完成：

```text
.venv
requirements.txt
setup.ps1
run.ps1
```

安装并验证：

```text
PySide6
mss
Pillow
numpy
PaddleOCR
Pydantic
python-dotenv
OpenAI SDK
pytest
```

---

## Phase 2 — 基础模型

实现：

```text
schemas.py
context/models.py
config/settings.py
```

先让：

```text
pytest
```

通过。

---

## Phase 3 — OCR

实现：

```text
capture
preprocess
OCR
normalize
diff
```

先不要接 GUI。

完成：

```text
image → OCR text
```

测试：

```text
smoke test
unit test
```

---

## Phase 4 — LLM

实现：

```text
Provider abstraction
OpenAI-compatible client
Prompt
JSON parser
Pydantic validation
Mock client
```

必须先用 Mock 测试。

然后使用配置好的真实 API 做连接测试。

---

## Phase 5 — Context / Analyzer

实现：

```text
Text
 ↓
Context
 ↓
Prompt
 ↓
LLM
 ↓
AnalysisResult
```

完成：

```text
unit tests
mock e2e
```

---

## Phase 6 — Region Selector

完成：

```text
全屏 overlay
鼠标框选
确认
取消
多显示器基础支持
```

---

## Phase 7 — Region Monitor

完成：

```text
interval
latest-only
OCR worker
text diff
debounce
generation
```

这是实时能力核心。

---

## Phase 8 — GUI

实现：

```text
Main Window
Floating panel
OCR editor
Settings
Status
Copy buttons
Pause
Clear
Reselect region
```

---

## Phase 9 — 集成

完整连接：

```text
UI
 ↓
Region
 ↓
Capture
 ↓
OCR
 ↓
Diff
 ↓
Context
 ↓
Debounce
 ↓
LLM
 ↓
Pydantic
 ↓
UI
```

---

## Phase 10 — Bug Fix

运行：

```powershell
pytest -q
```

修复所有失败。

再运行：

```powershell
python run.py
```

完成手动 smoke test。

---

## Phase 11 — 文档

最终更新：

```text
README.md
.env.example
PROJECT_SPEC.md
```

并记录：

```text
实际 Python 版本
实际依赖版本
安装问题
解决方案
```

---

# 93. Claude Code 的自主执行规则

这是最重要的一部分。

Claude Code 必须：

### 1

先检查环境和项目。

### 2

自动创建 / 修改代码。

### 3

自动安装依赖。

### 4

遇到依赖冲突：

```text
分析错误
→ 调整版本
→ 重新安装
→ 重新测试
```

不要马上停下来问用户。

### 5

遇到代码错误：

```text
读取 traceback
→ 定位根因
→ 修复
→ 重新运行
```

### 6

遇到 UI 问题：

```text
检查日志
→ 最小复现
→ 修复
→ 再启动
```

### 7

测试全部通过后再宣布完成。

### 8

如果真实 API Key 没有配置：

不要假装真实 LLM 已经验证。

应：

```text
Mock tests 完成
+
程序可启动
+
明确提示还需要用户配置 API Key 才能进行真实 AI 分析
```

---

# 94. Claude Code 不应频繁向用户提问

除非遇到真正无法自动解决的问题，例如：

```text
机器没有 Python
需要用户提供 API Key
需要用户批准系统弹出的权限
```

其他情况：

```text
不要因为代码结构选择、文件名、普通依赖问题而反复询问用户。
```

应该自主做合理决定。

---

# 95. Claude Code 自我检查清单

完成后逐项确认：

```text
[ ] Python 环境正确
[ ] 虚拟环境已建立
[ ] 依赖已安装
[ ] PaddleOCR 可以 import
[ ] OCR smoke test 通过
[ ] PySide6 可以启动
[ ] Region Selector 可以打开
[ ] 可以框选区域
[ ] mss 截图正常
[ ] OCR 不阻塞 GUI
[ ] 文本变化检测正常
[ ] debounce 正常
[ ] LLM Provider 可配置
[ ] API Key 没有硬编码
[ ] .env 被 gitignore
[ ] Mock LLM 正常
[ ] Pydantic schema 正常
[ ] Context 正常
[ ] stale request 不会覆盖新结果
[ ] 可以暂停监控
[ ] 可以恢复监控
[ ] 可以重新选择区域
[ ] 可以清空上下文
[ ] 可以复制建议回复
[ ] LLM 错误不会导致程序崩溃
[ ] OCR 错误不会导致程序崩溃
[ ] pytest 通过
[ ] python run.py 可以启动
[ ] README 完整
```

---

# 96. 最终人工验收流程

Claude Code 在实现完成后，要求用户实际完成：

## A. 启动

```powershell
python run.py
```

程序正常打开。

---

## B. 选择区域

点击：

```text
选择区域
```

或：

```text
Ctrl + Shift + S
```

框选当前聊天窗口。

---

## C. 开始监控

看到：

```text
监控中
```

---

## D. 让聊天发生变化

例如对方发送一条新消息。

程序应该：

```text
识别到变化
→ 等待 debounce
→ 显示分析中
→ 自动更新分析
```

无需用户再次点击“分析”。

---

## E. 检查上下文

让连续消息发生变化：

```text
A
B
C
```

最终 AI 应看到合理的：

```text
A
B
C
```

而不是只看到 C。

---

## F. 检查回复建议

至少有：

```text
2~3 个建议
```

并且可以复制。

---

## G. 检查暂停

点击：

```text
暂停
```

期间不应该继续 OCR。

---

## H. 检查恢复

点击：

```text
恢复
```

恢复正常。

---

## I. 检查 API 错误

使用错误 API Key。

程序：

```text
不能崩溃
```

且显示明确错误。

---

# 97. 最终性能验收

目标：

```text
UI 无明显卡顿
```

聊天区域静止时：

```text
不产生 LLM 请求
```

聊天文本变化时：

```text
只产生合理数量的 LLM 请求
```

快速连续 OCR 变化时：

```text
不会无限排队
```

旧 LLM 响应返回较晚时：

```text
不会覆盖新分析
```

---

# 98. 最终文件验收

至少有：

```text
PROJECT_SPEC.md
README.md
requirements.txt
.env.example
.gitignore
setup.ps1
run.ps1
run.py
app/
tests/
```

---

# 99. 最终汇报格式

Claude Code 完成后，不要只说：

```text
Done.
```

必须按照下面格式汇报：

## 1. 已完成功能

列出实际实现的功能。

## 2. 项目结构

列出核心目录和职责。

## 3. 环境

说明：

```text
Python version
PaddlePaddle version
PaddleOCR version
PySide6 version
```

## 4. 安装

告诉用户：

```powershell
.\setup.ps1
```

## 5. 运行

告诉用户：

```powershell
.\run.ps1
```

## 6. LLM 配置

说明：

```text
Provider
API Key
Base URL
Model
```

如何填写。

## 7. 测试结果

明确：

```text
pytest -q
```

通过多少测试。

## 8. 手动验证

说明是否实际验证：

```text
截图
OCR
实时变化检测
LLM
GUI
```

## 9. 已知问题

必须诚实列出。

## 10. 下一步

只给出 Roadmap，不要在本轮自动继续实现 Android。

---

# 100. 最终产品行为总结

最终产品必须能够做到：

```text
                    Windows Chat App
                           │
                           │
                    用户第一次框选
                           │
                           ▼
                 ┌───────────────────┐
                 │ Selected Region   │
                 └─────────┬─────────┘
                           │
                    每约 1 秒采样
                           │
                           ▼
                        Screenshot
                           │
                           ▼
                     Local PaddleOCR
                           │
                           ▼
                     Normalize Text
                           │
                           ▼
                      Text Diff
                           │
                     ┌─────┴─────┐
                     │           │
                   无变化        有变化
                     │           │
                     │           ▼
                     │        Debounce
                     │           │
                     │           ▼
                     │      Update Context
                     │           │
                     │           ▼
                     │        LLM Client
                     │           │
                     │           ▼
                     │    Structured JSON
                     │           │
                     │           ▼
                     │      Pydantic Validate
                     │           │
                     │           ▼
                     └──────► Floating UI
                                   │
                     ┌─────────────┼──────────────┐
                     │             │              │
                  表层意思       可能意图        情绪
                     │             │              │
                     └─────────────┼──────────────┘
                                   │
                              潜在诉求
                                   │
                              回复策略
                                   │
                           推荐回复 × 2~3
```

---

# 101. 最终开发原则

整个 V1 只围绕一件事：

> **让用户框选一次聊天区域后，程序能够持续、低打扰地理解最新可见聊天上下文，并自动给出有依据、有不确定性说明的语义分析和自然回复建议。**

不要为了技术复杂度而复杂。

不要因为未来 Android 而污染 Windows V1。

不要因为“AI Agent”这个名字而引入没必要的 Agent Framework。

不要因为“实时”而疯狂调用 OCR / LLM。

不要自动发送。

不要偷偷监听。

不要保存不必要的聊天数据。

优先保证：

```text
稳定
可运行
可配置
可扩展
隐私边界清晰
GUI 不阻塞
实时机制合理
```

---

# 102. 现在开始执行

**Claude Code，请从当前工作目录开始执行本项目。**

严格遵守本文档。

你的任务不是告诉我怎么做，而是：

```text
检查环境
→ 创建项目
→ 安装依赖
→ 编写代码
→ 测试
→ 运行
→ 修 Bug
→ 再测试
→ 启动验证
→ 完善 README
→ 最终汇报
```

执行过程中：

- 不要只输出伪代码；
- 不要停留在架构讨论；
- 不要把实现步骤重新交回给用户；
- 能自动解决的问题自行解决；
- 修改后必须实际运行；
- 遇到错误必须根据实际输出修复；
- 不要声称完成了没有验证的功能；
- 真实 API Key 缺失时使用 Mock 完成自动化验证，并明确真实 LLM 还需要用户配置 Key。

**本项目第一阶段只做到 Windows V1。**

**Android / Accessibility Service 放入下一迭代，不要在本轮实现。**
