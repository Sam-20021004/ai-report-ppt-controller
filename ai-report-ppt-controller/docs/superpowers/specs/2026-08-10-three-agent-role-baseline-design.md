# 三代理连接与角色基线设计

日期：2026-08-10
状态：已确认，待实施
适用项目：ReportAgent Studio Windows 本地 Web 应用

## 1. 目标

在现有 ReportAgent Studio 基础上建立第二阶段的三代理连接与固定角色基线：Windows 原生 Codex 负责规划、成果集成、最终文件生成和修订；WSL 内 Hermes 根据 Codex 计划执行检索、资料整理和技术分析任务；网页 ChatGPT 负责独立审核和终审。

本子项目只验证三端真实连接、角色契约和工作区交接。正式 PPT/Word 生成、完整审核循环和一键交付分别在后续里程碑实施。

## 2. 对现有设计的修正

本设计覆盖 `2026-08-09-codex-centric-demo-design.md` 中以下旧职责：

- Codex 不再只承担构建和修订，而是首要规划者和最终成果生成者。
- Hermes 不再承担 planner、reviewer 和 final reviewer，而是 Codex 计划下的任务执行者。
- 网页 ChatGPT 不再作为第二阶段工作流的 planner，而是 reviewer 和 final reviewer。
- 第一阶段已经实现的 ChatGPT Planner 能力继续保留为兼容功能，但不进入第二阶段默认工作流。

## 3. 已有基础

当前项目已经具备：

- Windows 本地 Web 服务、任务工作区、状态持久化、历史任务恢复、日志和文件下载。
- Chrome CDP/Bing 检索、来源归一化、去重、审计和人工复核。
- 结构化报告大纲和报告草稿。
- Codex CLI、Hermes HTTP 和 ChatGPT CDP 适配器基础。
- ChatGPT 页面健康检查、结构化 JSON 解析和错误分类。
- Hermes HTTP 桥 `http://127.0.0.1:7788`，当前 `/health` 可返回真实 Hermes 版本。
- 后端和静态前端自动化测试基线。

当前缺口是 Windows Codex 原生执行尚未完成真实验收、Hermes 任务结果契约尚未按新角色固化、ChatGPT 尚未切换为 reviewer，以及现有工作流状态仍体现旧职责。

## 4. 固定角色

### 4.1 Windows Codex

Codex 是第二阶段工作流的规划者、成果集成者和最终生成者，负责：

- 将用户目标转换为结构化计划。
- 将计划拆分为 Hermes 可执行的任务及依赖关系。
- 检查 Hermes 任务完成度、来源和中间产物。
- 在后续里程碑生成 PPT、Word、引用清单和交付包。
- 根据 ChatGPT 审核意见修订最终成果。

生产模式只允许调用 Windows 原生 Codex 命令，不使用 `wsl:` Codex 包装器。

### 4.2 WSL Hermes

Hermes 是任务执行者，负责：

- 接收单个或成组的 Codex 任务。
- 执行检索、资料整理、技术分析和证据提取。
- 将来源、分析结果和中间产物写入当前任务工作区。
- 返回结构化执行结果，不生成最终 PPT 或 Word。

Hermes 通过现有 HTTP 桥连接，不由 Windows 后端直接拼接并执行任意 WSL shell 命令。

### 4.3 网页 ChatGPT

ChatGPT 是独立审核者，负责：

- 审核事实、结构、表达、引用和交付质量。
- 输出评分、阻断问题、次要问题和修订要求。
- 在 Codex 修订后执行终审。

本子项目只建立 reviewer 契约并验证页面就绪，不发送正式审核内容。

## 5. 总体架构

```text
Web UI
  -> Role Baseline Service
       |- WindowsCodexAdapter -> Windows Codex CLI
       |- HermesAPIAdapter    -> 127.0.0.1:7788 -> WSL Hermes
       `- ChatGPTAdapter      -> Chrome CDP -> chatgpt.com
  -> Diagnostic Workspace
       |- diagnostic_plan.json
       |- hermes_execution.json
       |- diagnostic_final.md
       `- role_baseline_trace.json
```

Role Baseline Service 是三端诊断和最小工作区交接的唯一入口。适配器只处理各自传输协议；角色服务负责调用顺序、契约验证、文件边界、状态归一化和审计。

## 6. 组件设计

### 6.1 Windows Codex Adapter

在现有 `CodexCLIAdapter` 基础上增加 Windows 原生解析和诊断能力：

- 支持显式绝对路径或 PATH 中的 `codex` 命令。
- 生产连接拒绝 `wsl:` 前缀。
- `--version` 只证明可执行文件可启动，不等同于登录成功。
- 真实就绪检查由用户显式触发最小 `codex exec` 请求。
- 诊断请求要求返回 JSON，并在诊断工作区写入指定文件。
- stdout、stderr 和文件结果分别验证，不以退出码零单独判定成功。

### 6.2 Hermes HTTP Adapter

复用 `HermesAPIAdapter` 和既有 HTTP 契约：

- `GET /health` 验证桥和 Hermes 版本。
- `POST /run` 发送 `task_name`、`prompt`、Windows workspace 和 `extra_context`。
- 桥负责 Windows/WSL 路径转换。
- 返回值必须通过 Hermes 执行结果契约；若 Hermes 写入工作区，则仅接受本次调用新增或修改的文件。

### 6.3 ChatGPT Adapter

复用现有 CDP 页面检查：

- 验证 Chrome CDP、ChatGPT 页面、登录状态和输入框。
- 健康检查不发送消息。
- 保留现有 JSON 提取和页面错误分类能力。
- 新增 reviewer 契约类型，但正式审核调用留给后续里程碑。

### 6.4 Role Baseline Service

新增独立服务以避免继续扩大 `task_runner.py`：

- 生成诊断运行 ID 和受限工作区。
- 顺序执行 Codex 规划、Hermes 单项执行和 Codex 最终摘要。
- 验证返回契约和工作区文件。
- 记录每次尝试的执行模式、耗时、状态、错误代码和相对文件路径。
- 任一步失败立即停止，不启动下游步骤。

## 7. 数据契约

### 7.1 Codex 计划

```json
{
  "schema_version": "role.plan.v1",
  "objective": "验证三代理工作区交接",
  "tasks": [
    {
      "task_id": "task-001",
      "instruction": "根据给定材料生成简短事实摘要",
      "inputs": ["input/diagnostic_source.md"],
      "dependencies": [],
      "expected_outputs": ["execution/hermes_execution.json"],
      "acceptance_criteria": ["包含 summary、sources 和 errors"]
    }
  ],
  "final_outputs": ["final/diagnostic_final.md"]
}
```

计划至少包含一个任务。任务 ID 在单次计划内唯一；输入和输出必须是诊断工作区内的相对路径。

### 7.2 Hermes 执行结果

```json
{
  "schema_version": "role.execution.v1",
  "task_id": "task-001",
  "status": "success",
  "summary": "任务执行摘要",
  "sources": [],
  "artifact_paths": ["execution/hermes_execution.json"],
  "errors": []
}
```

`status` 只允许 `success` 或 `failed`。成功结果必须有非空 `summary`；所有产物路径必须位于诊断工作区。

### 7.3 ChatGPT 审核结果

```json
{
  "schema_version": "role.review.v1",
  "score": 0,
  "pass": false,
  "blocking_issues": [],
  "minor_issues": [],
  "revision_instruction": ""
}
```

本子项目只实现契约验证和 mock 测试，不发送真实审核请求。

### 7.4 诊断 trace

`role_baseline_trace.json` 记录：

- 诊断运行 ID、开始和结束时间。
- 三端配置模式和实际执行状态。
- Codex、Hermes、ChatGPT 的耗时和稳定错误代码。
- 工作区内的相对产物路径和 SHA-256。
- 是否使用 mock 或 fallback。

trace 不保存完整提示词、Cookie、令牌、授权头、浏览器 HTML 或工作区外的绝对路径。

## 8. 最小验证流程

1. 用户在页面显式点击“验证三代理基线”。
2. 系统检查诊断工作区和三端配置。
3. ChatGPT 只执行页面就绪检查。
4. Windows Codex 生成 `diagnostic_plan.json`。
5. 系统验证计划并选择首个无敏感信息的诊断任务。
6. Hermes 执行任务并生成 `hermes_execution.json`。
7. 系统验证 Hermes 结果、文件变化和路径边界。
8. Windows Codex 读取计划和 Hermes 结果，生成 `diagnostic_final.md`。
9. 系统生成 `role_baseline_trace.json` 并在页面显示状态、耗时、文件和修复提示。

该流程不调用正式搜索、不生成 PPT/Word，也不把诊断任务写入普通用户任务历史。

## 9. 配置与界面

配置继续复用现有字段，并增加工作流角色的只读展示：

- `codex_mode=cli` 和 Windows Codex 命令路径。
- `hermes_mode=api` 和 `http://127.0.0.1:7788`。
- `chatgpt_mode=cdp`、Chrome 主机和端口。
- `workflow_profile=three_agent_v2`。

设置页显示固定职责：

- Codex：规划、最终生成、修订。
- Hermes：任务执行。
- ChatGPT：审核、终审。

第二阶段默认工作流不再允许通过“主 Agent/审核 Agent”下拉框改变这些职责。兼容工作流可以保留旧设置，但必须明确标记为 legacy。

## 10. 错误处理

| 场景 | 错误代码 | 处理 |
|---|---|---|
| Windows Codex 不存在 | `codex_missing` | 停止并显示安装或路径提示 |
| Windows Codex 无执行权限 | `codex_access_denied` | 停止并显示权限及可执行文件路径 |
| Windows Codex 未登录 | `codex_login_required` | 停止并显示登录命令 |
| Codex 超时或输出无效 | `codex_timeout` / `codex_invalid_result` | 停止并保留脱敏诊断 |
| Codex 未写入预期文件 | `codex_artifact_missing` | 停止，不接受仅 stdout 成功 |
| Hermes 桥不可达 | `hermes_bridge_unavailable` | 停止并显示桥状态命令 |
| Hermes 超时或契约无效 | `hermes_timeout` / `hermes_invalid_result` | 停止并保留本次调用 trace |
| Hermes 产物越界 | `hermes_artifact_outside_workspace` | 拒绝结果并标记安全失败 |
| ChatGPT CDP 不可用 | `chatgpt_cdp_unavailable` | 基线失败，不发送消息 |
| ChatGPT 未登录或页面改变 | `chatgpt_login_required` / `chatgpt_page_changed` | 显示可执行修复提示 |

真实基线验收中，`mock`、`fallback`、`missing` 和 `failed` 均不计为成功。

## 11. 安全与隐私

- 诊断内容使用仓库内置的无敏感文本，不发送用户真实任务。
- 所有 Agent 只能访问本次诊断工作区。
- Windows 和 WSL 路径转换后再次验证工作区边界。
- subprocess 使用参数数组和 `shell=False`。
- 不读取、导出或记录 Codex/ChatGPT 登录凭据与浏览器 Cookie。
- HTTP 授权信息和 API token 在配置响应及日志中脱敏。
- 页面只显示必要诊断摘要，不显示完整 stdout、stderr 或页面 HTML。

## 12. 测试策略

### 12.1 单元测试

- Windows Codex 命令发现、访问失败、登录失败、超时、JSON 和文件验证。
- Hermes HTTP 健康检查、任务响应、路径转换、工作区文件恢复和契约失败。
- ChatGPT 页面就绪检查和 reviewer 契约。
- 三类角色契约的必填字段、枚举、路径和额外字段处理。
- trace 脱敏、相对路径和哈希。

### 12.2 集成测试

- 使用本地假 Hermes HTTP 服务验证 `/health` 和 `/run`。
- 使用假的 Windows Codex 进程验证 stdout、stderr、退出码和工作区写入组合。
- 使用假的 CDP 页面验证 ChatGPT 检查不发送消息。
- 完成无外部依赖的三步诊断流程。

### 12.3 真实冒烟测试

真实测试必须由用户显式触发，并要求：

- Windows Codex 已安装并登录。
- WSL Hermes 桥健康。
- 调试 Chrome 已打开且 ChatGPT 已登录。
- 诊断结果的三类文件和 trace 均通过契约验证。

真实冒烟测试不进入默认自动化测试套件。

## 13. 验收标准

1. 页面固定显示并正确描述 Codex、Hermes、ChatGPT 的新职责。
2. Windows 原生 Codex 能完成真实最小请求、返回结构化计划并写入诊断工作区。
3. WSL Hermes 能通过 HTTP 桥执行 Codex 任务并写入有效结构化结果。
4. Windows Codex 能读取 Hermes 结果并生成最终诊断文件。
5. ChatGPT 页面就绪检查成功且不发送消息。
6. 任一端使用 mock、fallback、缺失或失败时，真实基线验收不通过。
7. 所有产物均位于诊断工作区，trace 只包含相对路径且无敏感信息。
8. 后端完整测试、静态前端测试和语法检查全部通过。

## 14. 本子项目不包含

- 正式用户任务的完整三代理执行。
- 搜索 API 主通道。
- 可交付 PPTX 和 DOCX 构建。
- 真实 ChatGPT 审核和 Codex 修订循环。
- 一键 Demo、ZIP 打包、云部署、多用户、权限和团队协作。

## 15. 后续里程碑

基线验收通过后依次实施：

1. Codex 规划与 Hermes 多任务执行。
2. Codex 真实 PPT/Word 最终生成。
3. ChatGPT 审核、Codex 修订和 ChatGPT 终审。
4. 一键产品界面、恢复、质量展示和交付打包。
5. 真实端到端产品验收。
