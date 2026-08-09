# 使用说明

## 基本流程

1. 启动 Phase 1 服务。
2. 打开 `http://127.0.0.1:7860`。
3. 在左侧填写任务标题、PPT/Word 配置、检索边界和 Agent 配置。
4. 在“系统日志”页读取并保存规划器设置。
5. 点击“连接检测”检查 Codex、Hermes、Chrome CDP 和 ChatGPT。
6. 点击“创建任务”保存任务 JSON。
7. 点击“运行 Phase 1 工作流”写入流程日志。

## ChatGPT 规划方案2

相关环境变量如下：

```text
PLANNER_MODE=hermes
CHATGPT_MODE=mock
CHATGPT_USE_NEW_CHAT=1
CHATGPT_REPLY_TIMEOUT_S=600
```

- `PLANNER_MODE=hermes`：仅使用 Hermes Planner。
- `PLANNER_MODE=chatgpt`：优先使用 ChatGPT；CDP、登录、页面、回复、JSON 或规划契约失败时自动回退 Hermes。
- `CHATGPT_MODE=mock`：使用本地测试规划器，不访问 ChatGPT。
- `CHATGPT_MODE=cdp`：连接用户已登录的调试 Chrome。
- `CHATGPT_USE_NEW_CHAT=1`：每次规划使用新对话；设为 `0` 时复用当前对话。
- `CHATGPT_REPLY_TIMEOUT_S`：回复等待上限，允许范围为 30–1800 秒。

使用真实 ChatGPT 前，在 Windows 启动独立调试 Chrome：

```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="D:\chrome-debug-profile"
```

在该 Chrome profile 中登录 ChatGPT，然后调用 `POST /api/check/chatgpt` 或点击“检测 ChatGPT”。健康检查只确认 CDP、页面、登录状态和输入框是否可用，不发送测试消息。

每次任务会在 `review/planner_trace.json` 中记录首选规划器、最终规划器、回退原因、耗时、相对日志路径和规划哈希。ChatGPT 原始回复只保存在任务日志中，不写入任务状态。

## 隐私与安全

启用 ChatGPT 时，任务内容会发送到外部服务。请勿提交未经授权的敏感资料、商业秘密、个人信息、账号凭据或受限制的专利材料。

系统不会读取、导出或写入 Chrome Cookie、ChatGPT 令牌和浏览器 profile 内容。普通状态和审计记录也不保存这些信息。

## 输出位置

输出文件和日志默认位于：

```text
D:\codex-project\APP\outputs\ai-report-ppt-controller-runtime\tasks\{task_id}
```

如需改变位置，设置 `APP_STORAGE_DIR`。
