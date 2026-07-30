# Hermes + Codex + LangGraph 固定工作流设计

## 目标

在现有 ReportAgent Studio 中建立一条可恢复、可审计、职责固定的通用技术调研工作流：

- LangGraph 是唯一的工作流控制器。
- Codex 负责每个指定节点内的分析、判断、写作、文档生成和质量检查。
- Hermes 负责公开资料检索、原始文件下载、PDF/OCR/网页解析、证据定位和初步摘要。
- 人工只在“检索方案确认”和“最终导出确认”两个常规审批节点介入；异常和证据冲突按规则转入人工处理。
- Markdown 主报告是唯一内容母版，Word 和 PowerPoint 均从该母版派生。

首版面向通用技术调研报告，同时从一开始保留专利来源、公开日、优先权日、公开号、申请人和权利要求位置等扩展字段，为后续专利查新、竞争情报和 claim chart 工作流提供兼容基础。

## 已确认的设计决策

1. 工作流采用固定图，不使用 LLM Supervisor 动态选择 Agent。
2. 节点与 Agent 的映射固化在图定义中，首版不允许在普通用户界面中修改。
3. Hermes 不只检索，还负责下载、OCR/解析、正文与表格提取、初步摘要和原文定位。
4. 首版只自动接入公开来源；黑马、智慧芽等商业数据库以后通过 Hermes 控制的已登录浏览器会话接入。
5. 商业数据库的账号、密码、Cookie 和令牌不得进入 LangGraph 状态、提示词、证据包或普通任务日志。
6. Word/Markdown 主报告是唯一事实与结论母版，PPT 只从该母版派生。
7. 常规人工审批点固定为两个：检索方案确认和最终导出确认。
8. Hermes 补充检索最多两轮，Codex 自动修订最多两轮。
9. 本地首版使用 SQLite 保存 LangGraph checkpoint；多人或远程部署时再迁移到 PostgreSQL。
10. 首版复用现有 Codex CLI 和 Hermes HTTP 适配器；稳定版将 Codex 连接升级为 App Server，状态图和业务契约保持不变。

## 当前实现与改造边界

现有系统已经具备：

- `HermesAPIAdapter`：通过 HTTP 健康检查和 `/run` 接口调用 Hermes。
- `CodexCLIAdapter`：通过非交互 Codex CLI 在任务工作区运行一次性任务。
- `task_runner.py`：顺序执行规划、检索、写作、构建、审核和修订。
- 每任务独立工作区以及 `input`、`state`、`research`、`draft`、`review`、`output`、`logs` 等目录。
- Mock Hermes、Codex 和浏览器适配器及现有后端测试。

本设计用 LangGraph 替代 `task_runner.py` 中手写的流程控制职责，但不要求首版重写已有 Agent 适配器、文件下载接口、任务列表或前端基础框架。

首版不包含：

- 黑马、智慧芽等商业数据库的自动登录和生产接入；
- 自治 Agent 动态增加、删除或重排节点；
- 多租户权限、远程 PostgreSQL、高可用部署；
- 严格的专利新颖性、创造性、FTO 或侵权法律结论；
- 由 Hermes 直接编辑主报告、Word 或 PowerPoint；
- 未经人工批准即将草稿标记为正式交付物。

## 角色边界

### LangGraph

LangGraph 是确定性的流程运行时，不承担技术内容判断。它负责：

- 根据预定义图调用指定节点；
- 验证节点输出是否符合结构化模型；
- 保存 checkpoint、轮次、审批和错误状态；
- 执行条件路由、重试、暂停、恢复和终止；
- 生成幂等调用标识并避免重复执行已成功节点；
- 维护任务级审计轨迹。

### Codex

Codex 是分析与内容生产引擎，负责：

- 解析用户需求并形成检索任务书；
- 生成公开来源检索方案；
- 判断证据的相关性、充分性、可信度、冲突和缺口；
- 生成补充检索要求，但不直接改变流程；
- 生成 Markdown 主报告及其结构化大纲；
- 从主报告生成 Word 和 PowerPoint；
- 检查引用、事实、Word/PPT一致性和交付质量；
- 按结构化修订指令定向修改。

Codex 可以返回“证据充分”“需要补检”或“存在冲突”，但流程跳转由 LangGraph 的纯规则函数执行。

### Hermes

Hermes 是资料执行器，负责：

- 执行 LangGraph 交付的检索式和来源任务；
- 检索公开网页、官方专利数据库、论文和其他公开材料；
- 下载 PDF、网页快照、图片和附件；
- 对文本型 PDF、扫描件和网页进行解析或 OCR；
- 提取正文、表格、附图说明和必要元数据；
- 生成保守的初步摘要、证据标签和覆盖缺口；
- 保存原始文件并返回页码、章节、段落、附图或表格位置。

Hermes 不得生成最终报告结论，不得修改 `draft/`、`review/` 或 `output/` 中的正式内容。

### 人工

人工负责：

- 批准、修改或退回检索方案；
- 处理权威来源冲突、登录失效、验证码和达到自动循环上限的任务；
- 批准最终导出、要求修订、部分导出或取消发布。

## 固定节点与执行者映射

| 节点 | 执行者 | 主要输入 | 主要输出 |
|---|---|---|---|
| `initialize_task` | LangGraph/确定性代码 | 用户请求、上传材料 | 标准任务状态和工作区 |
| `analyze_request` | Codex | 用户请求、边界、受众 | `SearchPlan` |
| `approve_search_plan` | 人工中断 | `SearchPlan` | `ApprovalDecision` |
| `collect_sources` | Hermes | 已批准检索方案、补检要求 | `ResearchPackage` |
| `audit_evidence` | Codex | 证据包、任务成功标准 | `EvidenceAudit` |
| `route_evidence` | LangGraph/纯规则 | 审核结果、轮次 | 下一节点 |
| `draft_master_report` | Codex | 已审验证据、报告要求 | Markdown 主报告和 `ReportManifest` |
| `build_word` | Codex + 文档工具 | Markdown 主报告 | DOCX 草稿 |
| `build_ppt` | Codex + 演示文稿工具 | 同一 Markdown 主报告 | PPTX 草稿 |
| `quality_check` | Codex + 确定性校验 | 主报告、DOCX、PPTX、证据索引 | `QualityDecision` |
| `route_quality` | LangGraph/纯规则 | 质量结果、修订轮次 | 修订、人工或最终审批 |
| `revise_outputs` | Codex | 阻塞问题、主报告和派生产物 | 更新后的母版及派生产物 |
| `approve_export` | 人工中断 | 草稿、质量结果 | `ExportDecision` |
| `finalize` | LangGraph/确定性代码 | 已批准产物 | 正式清单、哈希和归档状态 |

节点映射由开发者在图定义中配置。Codex、Hermes和最终用户都不能在一次任务运行中改变映射。

## 工作流

```text
initialize_task
  -> analyze_request
  -> approve_search_plan
       -> 退回: analyze_request
       -> 取消: cancelled
       -> 批准: collect_sources
  -> audit_evidence
  -> route_evidence
       -> sufficient: draft_master_report
       -> insufficient 且 research_round < 2: collect_sources
       -> conflicting: human_evidence_review
       -> 达到补检上限: human_evidence_review
  -> build_word
  -> build_ppt
  -> quality_check
  -> route_quality
       -> passed: approve_export
       -> failed 且 revision_round < 2: revise_outputs
       -> 达到修订上限: human_quality_review
  -> approve_export
       -> 要求修订: revise_outputs
       -> 部分批准: finalize
       -> 全部批准: finalize
       -> 取消发布: cancelled_draft
  -> done
```

人工显式要求再次修订时可以增加一轮，但必须形成新的审批记录；自动恢复不得清零既有轮次。

## 工作区结构

```text
workspace/jobs/{task_id}/
  input/
    user_request.md
    uploads/
  state/
    request.json
    task.yaml
    status.json
    approvals.json
  prompts/
  research/
    raw/
    parsed/
    search_plan.json
    query_log.json
    sources.json
    evidence.json
    research_package.json
  draft/
    report_outline.json
    master_report.md
    report_manifest.json
  build/
    scripts/
    validation/
  review/
    evidence_audit_round_*.json
    quality_round_*.json
    revision_round_*.json
  output/
    draft/
    final/
    final_manifest.json
  logs/
    agents/
    workflow/
    security/
```

大文件和长正文不写入 LangGraph checkpoint。状态中只保存相对路径、结构化摘要、版本和 SHA-256 哈希。

## LangGraph 共享状态

共享状态采用严格的 Pydantic 模型，至少包含：

| 字段 | 类型或用途 |
|---|---|
| `schema_version` | 状态契约版本 |
| `task_id` | 唯一任务编号 |
| `request` | 标准化用户需求 |
| `current_node` | 当前或最后成功节点 |
| `status` | running、waiting、failed、cancelled、done |
| `search_plan` | 当前已生成方案及版本 |
| `search_approval` | 检索审批结果 |
| `research_round` | 检索轮次，首轮为 1 |
| `research_package_path` | Hermes 证据包相对路径 |
| `evidence_audit` | Codex证据判断 |
| `report_manifest` | 母版与派生产物索引 |
| `qa_result` | 当前质量检查结果 |
| `revision_round` | 自动修订轮次 |
| `export_approval` | 最终审批结果 |
| `human_action` | 暂停原因和恢复要求 |
| `retry_counters` | 每节点重试次数 |
| `errors` | 结构化错误记录 |
| `audit_events` | 关键状态变化索引 |

状态更新只允许通过节点返回值或人工恢复命令完成。任何 Agent 输出在进入共享状态前都必须通过模式验证。

## 结构化交接契约

### SearchPlan

`SearchPlan` 至少包含：

- 任务理解和明确排除项；
- 检索问题、关键词、同义词和上下位概念；
- 目标来源类型、时间范围、语言和地域；
- 每个检索问题的成功标准；
- 需要下载或提取的文件和数据类型；
- 风险、已知限制和需要人工确认的内容；
- 专利兼容字段，包括申请人、发明人、IPC/CPC、公开号和日期字段。

### ResearchPackage

Hermes 每轮返回：

```json
{
  "schema": "research.package.v1",
  "task_id": "task identifier",
  "research_round": 1,
  "queries": [],
  "sources": [],
  "evidence": [],
  "coverage_gaps": [],
  "failed_items": [],
  "created_at": "timestamp"
}
```

每条 `source` 至少包含：

- `source_id`
- `title`
- `source_type`
- `publisher`
- `authors`
- `publication_date`
- `url`
- `retrieved_at`
- `language`
- `local_file`
- `sha256`
- `parse_status`
- `parser`
- 可选专利字段：`publication_number`、`application_number`、`priority_date`、`applicant`、`jurisdiction`

每条 `evidence` 至少包含：

- `evidence_id`
- `source_id`
- `claim_supported`
- 必要的短摘录或保守释义
- `location.page`
- `location.section`
- `location.paragraph`
- `location.figure`
- `location.table`
- `verification_status`
- `limitations`

无法确定的页码、日期、申请人或法律状态必须为空并标记待核实，不得猜测补全。

### EvidenceAudit

Codex 返回：

```json
{
  "schema": "evidence.audit.v1",
  "status": "sufficient",
  "coverage": [],
  "source_quality_issues": [],
  "conflicts": [],
  "missing_items": [],
  "supplementary_queries": [],
  "blocking_reasons": []
}
```

`status` 只允许：

- `sufficient`
- `insufficient`
- `conflicting`
- `invalid_package`

LangGraph只根据枚举值、轮次和结构化阻塞项路由，不解析Codex自然语言来决定下一步。

### ReportManifest

`ReportManifest` 保存：

- Markdown 主报告路径和哈希；
- 结构化大纲路径；
- DOCX 草稿路径和哈希；
- PPTX 草稿路径和哈希；
- 引用清单路径；
- 每个关键事实关联的 `evidence_id`；
- 生成时间、生成节点和版本。

DOCX和PPTX不得形成独立事实源。如果派生产物与Markdown母版不一致，以母版和证据索引为准并触发质量失败。

### QualityDecision

`QualityDecision` 至少包含：

- `pass`
- `blocking_issues`
- `minor_issues`
- `citation_coverage`
- `word_ppt_consistency`
- `artifact_validation`
- `revision_instruction`

每个阻塞问题必须带类型、位置、证据和可执行修订要求。

## 文件权限与证据完整性

- Hermes只允许写入 `research/` 和 `logs/agents/hermes/`。
- Codex可读取任务材料和证据，但不得修改 `research/raw/`。
- 原始文件首次写入来源清单并登记哈希后视为只读。
- Codex输出只允许写入 `draft/`、`build/`、`review/`、`output/draft/` 和自身日志目录。
- `output/final/` 只由 `finalize` 确定性节点写入。
- 所有Agent文件路径必须先转换成任务目录内的规范化相对路径，再由安全连接函数解析。
- 越界路径、符号链接逃逸、凭据写入和原始证据哈希变化均视为安全错误。
- 最终报告每项关键事实必须关联至少一个 `evidence_id`；没有证据支撑的内容只能明确标记为分析、假设或待核实。

## 审批行为

### 检索方案确认

LangGraph在 `approve_search_plan` 使用 interrupt 暂停。允许：

- `approve`：批准当前版本；
- `edit_and_approve`：保存用户修改后的新版本并批准；
- `regenerate`：携带反馈返回Codex；
- `cancel`：终止并保留记录。

审批记录保存任务、方案版本、操作、时间和差异。只有已批准的方案可以发送给Hermes。

### 最终导出确认

LangGraph在 `approve_export` 暂停。允许：

- `approve_all`
- `approve_word_only`
- `approve_ppt_only`
- `request_revision`
- `cancel_publication`

审批前全部文件位于草稿目录并带草稿状态。`finalize` 只复制已批准文件，重新计算哈希并生成正式清单。

## 错误处理与恢复

| 错误类型 | 策略 |
|---|---|
| 网络超时或暂时不可用 | 自动重试2次，指数退避 |
| Agent结构化输出无效 | 携带验证错误重试1次 |
| 单个PDF/OCR/网页失败 | 记录失败项，继续其他来源 |
| 证据质量不足 | Hermes补检，最多2轮 |
| 权威来源冲突 | 转人工证据审核 |
| 登录、验证码或会话失效 | 不绕过，等待人工恢复 |
| 文件越权或凭据泄露风险 | 立即终止节点并记录安全事件 |
| checkpoint或关键输入损坏 | 任务失败，保留已有产物 |

每次节点调用使用 `task_id + node_name + round_number + input_version` 形成幂等键。进程重启后从最后成功checkpoint恢复；已经成功且输入版本未变化的节点不重复执行。

同一阻塞问题连续出现两次时停止自动修订。错误恢复不清除补检或修订计数。

## 可观测性与审计

每个节点记录：

- 节点名称、执行者和适配器类型；
- 开始、结束和耗时；
- 输入与输出模式版本；
- 输入和产物路径及哈希；
- 调用轮次、重试次数和幂等键；
- 路由决定及触发字段；
- 人工审批事件；
- 脱敏后的错误摘要。

日志不得保存密码、Cookie、Authorization头、API密钥或完整商业数据库会话信息。

## 分阶段集成

### 阶段一：LangGraph + 现有适配器

Python后端新增原生 `StateGraph`，复用：

- `HermesAPIAdapter`
- `CodexCLIAdapter`
- Mock Agent
- 现有任务工作区和文件接口

该阶段验证固定节点、证据契约、审批、checkpoint、恢复和最终交付闭环。Codex调用保持一次性任务模式。

### 阶段二：Codex App Server

保持节点、状态和文件契约不变，将Codex适配器升级为长期运行的App Server客户端：

- JSON-RPC/JSONL通信；
- Codex线程生命周期；
- 流式进度和事件映射；
- 审批请求映射；
- 会话恢复和更完整的错误信息。

App Server连接变化不得扩展Codex的流程控制权限。

### 阶段三：商业数据库浏览器适配

Hermes增加浏览器检索适配器，复用用户已登录会话：

- 凭据和Cookie只保留在本地浏览器配置中；
- 验证码和重新登录转人工；
- 不绕过站点使用条款或反自动化限制；
- 商业数据库结果仍需记录检索式、检索日期、公开号、导出文件和原文位置；
- 关键法律状态回到CNIPA、WIPO、EPO或USPTO等官方来源交叉核验。

## 测试策略

### 单元测试

- Pydantic状态和交接模型；
- 固定节点与Agent映射；
- 证据充分、不足、冲突和无效包路由；
- 补检和修订上限；
- 幂等键和checkpoint恢复；
- 路径规范化、写入权限和证据哈希；
- 引用到 `evidence_id` 的完整性；
- Word/PPT与Markdown母版一致性校验。

### Agent契约测试

- Hermes正常证据包；
- Hermes部分来源解析失败；
- Hermes缺少原文位置；
- Hermes或Codex返回格式错误；
- Codex要求补检；
- Codex发现冲突；
- Agent超时、失败和重试；
- 日志脱敏。

### 完整流程测试

- Mock Codex和Mock Hermes端到端执行；
- 两个审批点的暂停、修改、退回、批准和取消；
- SQLite checkpoint后杀进程并恢复；
- 补检两轮后转人工；
- 修订两轮后转人工；
- 部分导出Word或PPT；
- 未批准产物不进入正式目录；
- 重复恢复不重复下载或覆盖原始证据。

### 真实连接冒烟测试

- Hermes完成一次公开网页检索；
- Hermes下载并解析一个公开PDF；
- Codex生成并修订一份短检索方案；
- Codex根据证据包生成短篇Markdown主报告；
- 从同一母版成功生成DOCX和PPTX；
- 关键事实引用可回溯；
- 日志和checkpoint不包含凭据。

## 首版验收标准

首版必须同时满足：

1. 一个通用技术调研任务可以端到端完成。
2. 流程严格经过两个常规人工审批节点。
3. 节点与Agent映射固定且可通过测试验证。
4. 每项关键事实至少关联一个 `evidence_id`。
5. 每条证据可以追溯到来源、原始文件、哈希和具体位置。
6. Markdown是唯一内容母版，Word和PPT不存在独立事实。
7. Hermes不能修改报告，Codex不能修改原始证据。
8. 补检、自动修订和错误重试均有明确上限。
9. 进程重启后可从最后成功checkpoint恢复。
10. 未经最终批准的文件不能进入正式输出目录。
11. 最终输出包含DOCX、PPTX、来源清单、证据索引和审计记录。
12. 商业数据库只保留适配接口，不属于首版自动化验收范围。

## 参考

- OpenAI Codex App Server: https://developers.openai.com/codex/app-server
- OpenAI Codex harness integration guidance: https://openai.com/index/unlocking-the-codex-harness/
- LangChain multi-agent subagents: https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- LangGraph subgraph persistence: https://docs.langchain.com/oss/python/langgraph/use-subgraphs
