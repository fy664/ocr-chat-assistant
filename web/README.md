# 产品介绍页 · web/

「言外」的单页介绍页。纯静态、零依赖、零构建，不需要 Node 或任何 CDN。

## 打开

直接双击 `index.html`，或在本目录起一个本地服务：

```powershell
python -m http.server 8000
# 浏览器访问 http://127.0.0.1:8000
```

## 结构与实现

```
web/
├─ index.html             # 全部内容与内联 SVG 图标库
├─ register-protocol.ps1  # 注册/移除 yanwai:// 本地启动协议
├─ launch-desktop.vbs     # 协议启动器（隐藏窗口运行桌面端）
└─ assets/
   ├─ styles.css          # 设计令牌、布局、动画、响应式
   └─ main.js             # 滚动揭示 / 计数器 / 页签 / FAQ / 复制（旧演示代码已不再挂载）
```

- 视觉：深色极光 + 玻璃拟态 + 渐变描边，全部用 CSS 实现，没有位图素材。
- 动效：IntersectionObserver 滚动揭示、数字递增、光标辉光、Hero 卡片轻微倾斜；
  自动遵守 `prefers-reduced-motion`。
- 页面已改为 v2 按需解读的静态介绍；`main.js` 里仍保留旧版实时演示的 `SCRIPT`，
  但页面上已没有对应元素，不会发起网络请求。
- 离线：没有外链字体、CDN、统计脚本。中文使用系统字体（PingFang / 微软雅黑 / Noto Sans SC）。

## 从浏览器启动桌面端

介绍页上的「启动桌面端」按钮通过本地协议 `yanwai://launch` 唤起
`.venv\Scripts\pythonw.exe run.py`，不会弹出控制台窗口。

首次使用需要在项目根目录运行一次注册脚本（只写入当前用户注册表，不需要管理员权限）：

```powershell
.\web\register-protocol.ps1
```

- 只看会写入什么、不实际修改：`.\web\register-protocol.ps1 -DryRun`
- 取消注册：`.\web\register-protocol.ps1 -Remove`
- 启动器：`web/launch-desktop.vbs`（以项目根目录为工作目录、隐藏窗口启动）

协议注册失败或点击没有反应时，页面上的「没有反应？复制注册命令」可以复制该命令。

## 改文案与配色

| 想改什么 | 去哪 |
|---|---|
| 品牌名、标题、正文、FAQ | `index.html` |
| 主色 / 背景 / 字体 | `assets/styles.css` 顶部 `:root` |
| 旧版演示对话（已不再挂载） | `assets/main.js` 中的 `SCRIPT` |

页面底部链接指向仓库根目录的 `../README.md` 与 `../PROJECT_SPEC.md`，
如果在本地移动了本目录，记得同步修改。
