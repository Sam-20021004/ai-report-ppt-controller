# Codex 主导的一键 Demo 产品设计

日期：2026-08-09
状态：已确认，待实施
运行环境：Windows 本地 Web 应用，`http://127.0.0.1:7860`

## 1. 目标

在现有 ReportAgent Studio 基础上交付一个可稳定演示、可实际交付成果的本地产品闭环。用户点击“一键运行完整 Demo”后，系统完成真实检索、规划、证据整理、内容撰写、PPT/Word 构建、质量评审、自动修订、终审和交付打包。

Demo 面向技术与管理混合观众，不限制总耗时，优先保证流程真实、结果可追溯和交付质量。

## 2. 已确认的产品选择

- 采用 Codex 主导架构。
- Hermes 负责 planner、reviewer 和 final reviewer。
- 真实 Codex 负责研究整合、内容撰写、PPT/Word 构建和自动修订。
- Codex 失败时允许切换内置高质量构建器，并明确标记 fallback。
- 实时检索为必选步骤，搜索 API 为主通道，Chrome CDP 为回退通道。
- 首个版本继续运行在 Windows 本地 7860 Web 应用。
- 默认业务场景为通用企业技术调研与汇报。
- 每次任务必须交付 PPT、Word 报告、来源清单和质量评审包。

## 3. 总体架构

```text
一键 Demo
  -> 本地预检
  -> Hermes 结构化规划
  -> 搜索网关执行实时检索
       |- 搜索 API 主通道
       `- Chrome CDP 回退
  -> Codex 整理证据、撰写内容并构建 PPT/Word
  -> Hermes 初审
  -> Codex 自动修订（最多两轮）
  -> Hermes 终审
  -> 打包并提供下载
```

### 3.1 Web 应用

负责创建任务、展示环境状态与流程进度、呈现质量结果，并提供交付物下载。Web 应用不承担内容生成。

### 3.2 编排器

负责状态机、步骤输入输出、超时与恢复、任务日志、产物目录和最终清单。每个阶段写入可恢复状态，不把内容创作逻辑嵌入编排器。

### 3.3 Hermes

负责三类只读决策任务：

- planner：拆解任务、提出检索问题和交付结构。
- reviewer：检查事实、结构、格式和交付质量。
- final reviewer：对修订后的最终交付进行独立质量门控。

Hermes 不直接修改最终 PPT 或 Word 文件。

### 3.4 搜索网关

向编排器提供统一检索接口。搜索 API 为主通道；API 不可用或结果不足时切换 Chrome CDP。输出统一证据对象，不把不同搜索实现暴露给下游消费者。

### 3.5 Codex

真实 Codex CLI 是主要执行者，负责：

- 对检索证据进行去重、归类和引用映射。
- 生成报告内容、PPT 分镜和 Word 结构。
- 创建可复现的 PPT/Word 构建脚本并执行。
- 根据 Hermes 的阻断问题修改最终文件。

### 3.6 内置高质量构建器

仅在 Codex 重试失败后启用。它必须生成可交付文件，并在任务状态、manifest 和页面中标记 `fallback_builder=true`，避免把回退结果误报为真实 Codex 产物。

## 4. 首个里程碑：本地真实 Codex 响应

完整产品开发前，必须先完成以下最小验收：

1. 检测 WSL 内 Codex CLI 与登录状态。
2. 通过 `wsl:/home/cincin/.local/bin/codex-wsl.sh` 执行最小 `codex exec` 请求。
3. Codex 返回结构化 JSON。
4. Codex 在 Windows 任务工作区写入验证文件。
5. `/api/check/codex` 返回 `status=success`，页面不再显示 `mock`。
6. 未登录、凭据失效、超时和输出无效均给出可执行的修复提示。

只有该里程碑通过后，才把 Codex 接入完整 Demo 工作流。

## 5. 一键 Demo 页面

首页增加“运行完整 Demo”入口，使用预置的通用企业技术调研任务，不要求用户填写表单。

### 5.1 运行环境

显示 Hermes、Codex、搜索 API、Chrome CDP 和输出目录状态。状态必须区分 `success`、`mock`、`fallback`、`missing` 和 `failed`。

### 5.2 实时流程

展示以下步骤与耗时：

`预检 -> 规划 -> 实时检索 -> 证据整理 -> 内容撰写 -> PPT/Word 构建 -> 评审 -> 修订 -> 终审 -> 打包`

每一步可展开查看输入摘要、输出文件、日志和错误。

### 5.3 结果与质量

展示来源数量、有效来源、域名分布、PPT 页数、Word 字数、Hermes 分数、阻断问题、执行模式和终审结论。

### 5.4 交付下载

必须提供：

- `final_presentation.pptx`
- `final_report.docx`
- `sources.xlsx` 或 `sources.json`
- `quality_review.json`
- 完整 ZIP 交付包

## 6. 数据契约

### 6.1 搜索证据

每条来源至少包含：

```json
{
  "source_id": "stable-id",
  "title": "来源标题",
  "url": "https://example.com",
  "publisher": "发布者",
  "published_at": "2026-08-09",
  "retrieved_at": "2026-08-09T12:00:00+08:00",
  "snippet": "相关摘录",
  "query_id": "query-1",
  "provider": "api | chrome_cdp",
  "status": "verified | candidate | rejected"
}
```

### 6.2 Codex 构建结果

Codex 必须返回结构化结果，至少包含执行模式、生成文件、构建脚本、页数或字数、引用数量和错误列表。最终文件必须实际存在于任务工作区。

### 6.3 质量评审

Hermes 评审必须包含数值 `score`、布尔 `pass`、`blocking_issues`、`minor_issues` 和 `revision_instruction`。工作区回退只接受本次调用新增或修改且满足契约的文件。

## 7. 错误处理与恢复

- 搜索 API 失败或结果不足：切换 Chrome CDP。
- 搜索 API 与 Chrome CDP 均失败：停止任务并保留检索日志，不生成无来源报告。
- Codex 失败或超时：自动重试一次；仍失败则切换内置构建器。
- Hermes 返回 diff、说明文本或超时：沿用本次工作区产物指纹恢复机制。
- 评审未通过：Codex 最多自动修订两轮。
- 连续两轮出现相同阻断问题：进入 `needs_review`，不继续消耗执行时间。
- 页面刷新或服务重启：可重新读取任务状态和已有产物。

## 8. 质量标准

- 实时检索不少于 8 个有效来源，覆盖不少于 3 个独立域名。
- 每条来源保留标题、URL、日期、检索时间、摘录和引用映射。
- PPT 默认 10 页，每页一个结论，包含来源脚注和讲者备注。
- Word 报告目标 2500–4000 字，结论与 PPT 一致。
- Hermes 初审和终审均达到 85 分，且不存在阻断问题。
- PPT 检查页数、空页、文本溢出、表格、乱码、讲者备注和引用完整性。
- Word 检查结构、字数、引用、标题层级和空段落。
- 所有数据和图表标注来源、口径和检索日期。

## 9. 测试与验收

### 9.1 自动化测试

- 搜索 API 成功、失败、结果不足和 CDP 回退。
- Codex 登录、健康检查、结构化响应和工作区写入。
- Codex 超时、重试和构建器回退。
- Hermes planner/reviewer/final reviewer 的结构化和工作区回退。
- PPT/Word 结构与质量检查。
- 页面一键创建、进度恢复、失败提示和下载入口。

### 9.2 本地响应验收

真实 Codex CLI 返回 JSON、写入工作区文件，页面显示 `success`。

### 9.3 完整产品验收

一键 Demo 完成实时检索、证据整理、PPT/Word 构建、最多两轮修订、终审和 ZIP 下载。最终结果必须达到质量门槛；如果使用回退构建器，页面和交付清单必须明确标注。

## 10. 范围边界

首个版本不包含多用户、权限管理、云部署、数据库任务队列和团队协作功能。任务仍以本地文件工作区持久化，优先完成单机单用户的完整高质量闭环。
