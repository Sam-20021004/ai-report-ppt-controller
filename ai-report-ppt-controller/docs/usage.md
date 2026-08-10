# 使用说明

## 三代理 V2 角色

本阶段固定职责如下：

- Windows Codex：规划、最终生成和后续修订。
- WSL Hermes：按照 Codex 规划执行任务。
- 网页 ChatGPT：审核和终审。本阶段只验证网页端就绪状态，不发送消息。

`WORKFLOW_PROFILE=three_agent_v2` 目前用于启用并展示这套固定角色基线，不会静默替换已有的生产任务工作流。旧版表单中的“主 Agent”和“审核 Agent”仅保留为兼容配置，在三代理基线中不生效。

## 推荐配置

```env
WORKFLOW_PROFILE=three_agent_v2
CODEX_MODE=cli
CODEX_COMMAND=codex
CODEX_EXEC_ARGS=exec
CODEX_DIAGNOSTIC_TIMEOUT_S=300
HERMES_MODE=api
HERMES_ENDPOINT=http://127.0.0.1:7788
HERMES_HEALTH_PATH=/health
HERMES_RUN_PATH=/run
CHATGPT_MODE=cdp
CHROME_CDP_HOST=127.0.0.1
CHROME_CDP_PORT=9222
```

`CODEX_COMMAND` 必须指向 Windows 原生 Codex，三代理 V2 明确拒绝 `wsl:` 前缀。Hermes 继续运行在 WSL 内，由 Windows 通过本机 HTTP 桥接地址访问。

## 启动与就绪检查

1. 在 Windows 终端确认 `codex --version` 可以运行，并在需要时完成 `codex login`。
2. 在 WSL 启动 Hermes HTTP 桥接服务，确认 Windows 可访问 `http://127.0.0.1:7788/health`。
3. 用独立调试配置启动 Chrome：

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --remote-allow-origins=* `
  --user-data-dir="D:\chrome-debug-profile"
```

4. 在该 Chrome 配置中登录 ChatGPT，并保持 ChatGPT 页面可用。
5. 启动应用，打开 `http://127.0.0.1:7860`。

`POST /api/check/chatgpt` 以及三代理基线中的 ChatGPT 就绪检查只检查 CDP、页面、登录状态和输入框可用性，不会发送测试消息。

## 运行三代理连接基线

在“系统日志”页点击“运行真实连接基线”，或显式调用：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:7860/api/check/role-baseline `
  -ContentType application/json `
  -Body '{}'
```

页面加载、普通连接检查和 `checkAll()` 都不会自动运行该基线。基线按以下顺序执行：

1. 验证 Windows Codex、WSL Hermes 和网页 ChatGPT 都是真实就绪状态。
2. Codex 写入 `diagnostic_plan.json`。
3. Hermes 按计划写入 `hermes_execution.json`。
4. Codex 读取前两项产物并写入 `diagnostic_final.md`。
5. 系统写入脱敏的 `role_baseline_trace.json`。

诊断目录位于：

```text
{APP_STORAGE_DIR}\workspace\diagnostics\{run_id}\
```

只有 `success` 算真实通过；`mock`、`fallback`、`missing` 和 `failed` 都会使基线失败。系统在首个失败处停止，同时尽可能保留审计轨迹。

## 隐私与产物边界

基线只把仓库自有的无敏感诊断句子发送给 Codex 和 Hermes，不使用真实用户任务内容，也不会向 ChatGPT 发送消息。审计轨迹不保存 Cookie、令牌、Authorization 标头、完整网页 HTML、提示词、stdout/stderr 或诊断目录外的绝对路径。

所有被接受的产物必须满足以下条件：

- 路径相对于本次诊断工作区，不能使用绝对路径或 `..`。
- 文件必须在当前代理调用中创建或发生变化。
- JSON 产物必须同时满足严格契约，并与代理返回的结构化结果一致。
- 审计清单记录相对路径、文件大小和 SHA-256。

## 常见错误

| 错误码 | 处理建议 |
|---|---|
| `codex_windows_required` | 将 `CODEX_COMMAND` 改为 Windows 原生 Codex，不能使用 `wsl:`。 |
| `codex_access_denied` | 检查 WindowsApps 别名、可执行文件权限或重新安装 Codex。 |
| `codex_login_required` | 在 Windows 终端运行 Codex 登录流程。 |
| `hermes_bridge_unavailable` | 确认 WSL 桥接服务已启动并监听配置地址。 |
| `hermes_auth_failed` | 核对桥接认证环境变量和请求配置。 |
| `chatgpt_cdp_unavailable` | 使用远程调试参数启动 Chrome。 |
| `chatgpt_login_required` | 在调试用 Chrome 配置中登录 ChatGPT。 |
| `artifact_not_changed` | 检查代理是否确实写入指定诊断文件。 |
| `artifact_result_mismatch` | 检查代理返回 JSON 是否与落盘 JSON 完全一致。 |

## 真实联调测试

测试默认跳过，不会产生外部请求。仅在三端配置完成后显式运行：

```powershell
$env:ROLE_BASELINE_LIVE = "1"
python -m pytest backend/tests/test_role_baseline_live.py -v -p no:cacheprovider `
  --basetemp=D:\codex-project\APP\tmp\pytest-role-live-real
Remove-Item Env:ROLE_BASELINE_LIVE
```

只有 Windows Codex、WSL Hermes、网页 ChatGPT 就绪检查以及两次 Codex/一次 Hermes 实际交接全部成功时，该测试才通过。
