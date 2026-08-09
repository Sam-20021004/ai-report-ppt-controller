# ChatGPT 规划方案2稳定化设计

## 目标

在现有 AI Report & PPT Agent Controller 顺序工作流中，将 ChatGPT 网页版稳定地接入为首选规划器，并在 ChatGPT 不可用或规划结果无效时自动回退到 Hermes Planner。

本阶段交付一个可稳定运行、可配置、可审计、可测试的规划环节，不引入 LangGraph，也不改变 Hermes 检索/写作/审核和 Codex 文件构建/修订的既有职责。

## 当前基线与主要问题

2026 年 8 月 9 日的未提交增量已经包含：

- `ChatGPTAdapter` 与 `MockChatGPTAdapter`；
- 通过 Chrome CDP 操作 `chatgpt.com` 的浏览器交互；
- ChatGPT 规划提示词和规划器选择配置；
- 在 `task_runner.py` 中按 `planner_mode` 选择 ChatGPT 或 Hermes。

现有增量需要稳定化的原因如下：

1. `chatgpt_use_new_chat` 和 `chatgpt_reply_timeout_s` 已进入配置模型，但尚未完整传递到真实调用。
2. ChatGPT 回复解析失败后仍可能返回适配器级成功，下游会收到空规划而不是触发回退。
3. 当前完成判定只观察“停止回答”按钮，存在未开始生成就提前判定完成、误读上一轮回复的风险。
4. ChatGPT 健康检查主要确认 CDP 可连接，尚未确认登录态、输入框和页面可操作性。
5. 回退决策分散在顺序工作流中，不利于独立测试和后续迁移。
6. 当前实际运行的静态开发服务器有独立配置默认值，需要与 Pydantic 配置模型同步。
7. 现有默认回归测试覆盖原工作流，但未覆盖 ChatGPT 规划、契约校验和回退路径。

## 已确认的设计决策

1. 本阶段采用“稳定可用版本”范围，而不是只完成演示，也不提前整合 LangGraph。
2. `planner_mode=chatgpt` 表示“ChatGPT 优先，失败自动回退 Hermes”；`planner_mode=hermes` 表示仅使用 Hermes。
3. ChatGPT 只负责生成规划，不执行检索、写作、文档构建或审核。
4. ChatGPT 失败不能静默；任务必须记录回退原因和最终采用的规划器。
5. 设置界面提供规划器选择、新建对话开关和回复超时设置，并支持 ChatGPT 单独连接检测。
6. 当前实际提供服务的 `frontend/static/` 是本轮界面交付对象；未接入当前运行入口的 React 设置占位组件不在本轮扩展范围。
7. 根目录 `server.js` 属于另一套检索/PPT 应用，本轮不修改其中现有未提交改动。

## 方案比较

### 方案一：最小补丁

直接在 `task_runner.py` 中补充配置传递和 `try/except` 回退。

优点是改动少；缺点是契约验证、错误分类、任务审计和测试边界仍与工作流耦合，后续迁移成本高。

### 方案二：稳定化适配层

新增统一规划契约和规划服务，由规划服务调用 ChatGPT、验证结果、决定回退并生成审计记录。`task_runner.py` 只消费标准化结果。

该方案职责清晰，能够独立测试，同时不要求重写现有工作流。本设计采用此方案。

### 方案三：通用规划器链

建立可配置的多规划器优先级、重试和路由框架。

该方案扩展性最高，但当前只有 ChatGPT 和 Hermes 两种规划器，通用链会引入不必要的配置和抽象，暂不采用。

## 总体架构

```text
界面与配置
  ├─ ChatGPT 优先，失败回退 Hermes
  └─ 仅使用 Hermes
          │
          ▼
Planner Service
  ├─ ChatGPTAdapter：浏览器交互与回复解析
  ├─ Planner Contracts：规划结构验证与归一化
  ├─ HermesAdapter：首选或回退规划器
  └─ Planner Trace：执行与回退审计
          │
          ▼
NormalizedPlannerResult
          │
          ▼
现有检索、写作、构建与审核流程
```

规划器调用、契约验证和回退均在 Planner Service 内完成。下游不需要识别 ChatGPT 或 Hermes 的原始返回结构，也不根据自然语言错误文本决定流程。

## 组件设计

### Planner Contracts

新增独立的规划契约模块，负责：

- 定义标准规划结构；
- 验证必需字段、字段类型和最小内容要求；
- 将合法输入归一化为稳定结构；
- 返回机器可读的验证错误；
- 定义规划执行审计结构。

标准规划至少包含：

| 字段 | 要求 |
|---|---|
| `task_understanding` | 非空字符串 |
| `outline` | 3–6 项；每项包含非空 `section` 和 `goal` |
| `search_questions` | 至少 3 个非空问题 |
| `figures_needed` | 字符串数组，可为空 |
| `risks` | 字符串数组，可为空 |
| `success_criteria` | 字符串数组，至少 1 项 |
| `language` | 非空字符串 |

提示词要求 `search_questions` 覆盖技术现状、竞争格局和风险。首版通过明确提示词和至少三项的结构校验保证基本覆盖，不使用关键词猜测每个问题所属类别，避免对中英文和不同技术领域形成脆弱规则。

验证失败时，契约模块返回字段路径与错误代码，例如 `outline.too_short`、`outline.0.goal.required` 或 `search_questions.type_error`。原始回复不进入契约错误文本。

### ChatGPTAdapter

`ChatGPTAdapter` 只负责与 ChatGPT 网页交互并返回结构化适配器结果：

- 使用配置中的 CDP 主机和端口；
- 使用 `chatgpt_use_new_chat` 决定是否创建新对话；
- 使用 `chatgpt_reply_timeout_s` 控制本次回复等待上限；
- 在发送前记录当前 assistant 消息数量；
- 发送后先等待新的 assistant 消息出现，再等待该消息停止更新并确认生成控件消失；
- 只提取本次新出现的最后一条 assistant 消息；
- 将页面交互错误分类为稳定错误代码；
- 解析 JSON，但不自行决定 Hermes 回退。

适配器成功必须同时满足：消息确实由本次发送产生、回复非空、JSON 可解析。规划业务契约是否有效由 Planner Contracts 判定。

适配器错误代码至少区分：

- `cdp_unavailable`
- `chatgpt_page_unavailable`
- `login_required`
- `composer_not_found`
- `send_failed`
- `reply_not_started`
- `reply_timeout`
- `empty_reply`
- `invalid_json`
- `page_changed`

选择器仍采用中英文和稳定属性的有限组合。页面结构异常时立即返回结构化失败，不通过宽泛选择器点击不确定元素。

### Planner Service

新增 Planner Service 作为唯一规划入口。它接收任务请求、工作区、设置、ChatGPT 适配器和 Hermes 适配器，返回：

```json
{
  "plan": {},
  "trace": {
    "requested_mode": "chatgpt",
    "primary_planner": "chatgpt",
    "selected_planner": "hermes",
    "fallback_used": true,
    "fallback_reason_code": "reply_timeout",
    "fallback_reason": "ChatGPT reply did not complete within 600 seconds.",
    "attempts": [],
    "started_at": "timestamp",
    "completed_at": "timestamp"
  }
}
```

Planner Service 执行规则：

1. `planner_mode=hermes` 时只调用 Hermes，Hermes 失败则任务失败。
2. `planner_mode=chatgpt` 时先调用 ChatGPT。
3. ChatGPT 适配器失败、JSON 解析失败或规划契约失败时调用 Hermes。
4. Hermes 回退结果同样必须通过规划契约；若无效，则任务失败并同时保留两次尝试的脱敏错误摘要。
5. ChatGPT 成功且契约有效时不调用 Hermes。
6. Planner Service 不在首版内对同一规划器自动重复调用，避免重复发送网页消息和不可控等待；Hermes 回退即为第二次且最后一次规划尝试。

`attempts` 只保存规划器名称、状态、错误代码、耗时和相对日志路径，不保存完整提示词、原始回复、Cookie、令牌或浏览器会话信息。

### task_runner 集成

`task_runner.py` 不再包含 ChatGPT/Hermes 返回结构分支和回退判断。规划步骤只调用 Planner Service，然后：

- 将标准化 `plan` 写入既有 `draft/outline.json`；
- 将检索问题写入既有 `research/search_queries.json`；
- 将 `planner_trace` 写入任务步骤输出和独立审计文件；
- 使用最终规划继续现有 Phase 2 契约生成和后续流程。

现有任务步骤编号、工作区目录和后续 Hermes/Codex 职责保持不变。

## 配置设计

配置模型和静态开发服务器默认配置必须包含相同字段与默认值：

| 配置项 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `planner_mode` | `hermes` 或 `chatgpt` | `hermes` | `chatgpt` 表示优先 ChatGPT 并允许 Hermes 回退 |
| `chatgpt_mode` | `mock` 或 `cdp` | `mock` | 真实浏览器或测试适配器 |
| `chatgpt_use_new_chat` | 布尔值 | `true` | 每次规划前创建新对话 |
| `chatgpt_reply_timeout_s` | 整数 | `600` | 等待回复的秒数，允许范围 30–1800 |

配置更新继续通过 `/api/config/update`。服务端必须执行类型和范围校验，不能依赖界面输入约束。API 返回配置时继续遮蔽 `api_token`。

## 健康检查

新增 `POST /api/check/chatgpt`，FastAPI 和静态开发服务器保持同一响应语义。检查内容包括：

1. Chrome CDP 可连接；
2. 存在或能够打开 `chatgpt.com` 页面；
3. 页面未显示明确登录入口，且存在可用输入框；
4. 返回页面可操作状态和脱敏诊断，不发送测试消息。

健康检查不把“页面可打开”描述为“规划一定成功”。真实回复仍由任务执行路径验证。

## 界面设计

当前静态界面的设置入口改为可编辑配置面板，包含：

- 规划器：`ChatGPT 优先，失败回退 Hermes` / `仅使用 Hermes`；
- ChatGPT 模式：`Mock` / `Chrome CDP`；
- 每次使用新对话：开关；
- 回复超时：30–1800 秒数值输入；
- 保存配置按钮；
- 检测 ChatGPT 按钮；
- 最近一次检测结果。

选择“仅使用 Hermes”时保留 ChatGPT 配置但将其标记为当前不生效。界面不显示、读取或保存 Cookie、访问令牌和浏览器配置目录内容。

静态界面是本轮唯一必须更新并测试的界面。React 源码中的设置占位组件继续保持未接入状态，避免在两个尚未统一的界面实现之间复制业务逻辑。

## 文件与审计

每个任务新增：

```text
workspace/jobs/{task_id}/
  review/
    planner_trace.json
  logs/
    chatgpt_planner.log
    hermes_planner.log
```

日志路径写入状态时必须转换为任务目录内的相对路径。ChatGPT 原始回复只保存在 agent 日志中；任务状态只保留截断且脱敏的错误摘要。规划审计至少记录：

- 请求的规划模式；
- 首选与最终规划器；
- 是否回退及原因代码；
- 每次尝试的开始时间、结束时间和耗时；
- 规划契约版本；
- 最终规划文件的 SHA-256；
- 相对日志路径。

## 安全与隐私

- 只通过现有 CDP 会话使用用户已登录的 ChatGPT 页面，不读取或导出 Cookie。
- 日志不得包含 Authorization、API key、Cookie、浏览器 profile 内容或完整页面 HTML。
- ChatGPT 页面 URL 在审计中只保留源站和必要的对话标识摘要，不保存查询参数。
- 所有日志和审计路径必须限制在任务工作区内。
- 原始用户任务会发送给 ChatGPT 网页版；界面和使用文档必须明确提示用户不要提交不允许发送到外部服务的敏感资料。
- 回退到 Hermes 不改变数据边界；Hermes 接收的仍是现有规划提示和任务上下文。

## 错误处理

| 场景 | 处理 |
|---|---|
| CDP 不可用 | 记录 `cdp_unavailable`，回退 Hermes |
| ChatGPT 未登录 | 记录 `login_required`，回退 Hermes |
| 找不到输入框或发送失败 | 记录对应页面交互错误，回退 Hermes |
| 新回复未出现 | 记录 `reply_not_started`，回退 Hermes |
| 回复超时 | 保存已获得的部分原始日志，记录 `reply_timeout`，回退 Hermes |
| 回复为空或 JSON 无效 | 记录 `empty_reply` 或 `invalid_json`，回退 Hermes |
| 规划契约无效 | 记录字段级验证错误摘要，回退 Hermes |
| Hermes 回退失败 | 规划步骤失败，任务状态为 `failed` |
| 审计文件写入失败 | 规划步骤失败，不继续使用缺少审计的规划 |

回退是显式的工作流结果，不以异常堆栈作为正常控制流。异常堆栈只进入本地诊断日志。

## 测试策略

### 契约单元测试

- 完整合法规划通过并得到标准化结果；
- 缺少必需字段、错误类型、空文本、章节过少或过多时返回稳定错误代码；
- 多余字段不进入标准化输出；
- 审计结构不接受绝对路径或敏感字段。

### ChatGPT 适配器单元测试

- 配置的新建对话和超时值传入浏览器调用；
- JSON 代码块、纯 JSON 和带少量说明文字的平衡 JSON 可解析；
- 无效 JSON 返回 `invalid_json`；
- 只提取发送后新增的 assistant 消息；
- 未开始、超时、空回复和页面结构变化返回对应错误代码。

浏览器单元测试使用可控的页面替身，不连接真实 ChatGPT，不把 mock 行为当作页面成功的唯一证据。

### Planner Service 单元与集成测试

- Hermes 模式不调用 ChatGPT；
- ChatGPT 成功且契约有效时不调用 Hermes；
- ChatGPT 适配器失败时回退 Hermes；
- ChatGPT 规划契约失败时回退 Hermes；
- Hermes 回退失败时任务失败；
- `planner_trace` 正确记录选用规划器、原因、耗时、相对路径和哈希；
- mock 完整工作流能够生成现有 Phase 2 文件且不破坏原回归测试。

### API 与界面测试

- 两套服务入口读取和更新相同的 ChatGPT 配置；
- 超时越界、错误枚举和错误类型被拒绝；
- `/api/check/chatgpt` 返回稳定结构；
- 静态设置面板能够载入、修改和保存配置；
- 连接检测结果能显示，且界面不渲染敏感配置。

### 真实浏览器冒烟测试

真实 ChatGPT/CDP 测试必须显式启用，并要求：

- 本机已启动调试 Chrome；
- 用户已在指定 profile 登录 ChatGPT；
- 测试发送无敏感信息的最小规划请求；
- 测试只验证获得合法规划或结构化失败，不进入默认回归套件。

## 验收标准

1. 用户可在静态设置界面选择 ChatGPT 优先或仅 Hermes，并持久化配置。
2. ChatGPT 成功时，后续流程消费通过契约验证的标准规划。
3. 所有规定的 ChatGPT 失败场景均自动回退 Hermes，并在任务审计中可见。
4. ChatGPT 和 Hermes 都失败时，任务明确失败，不生成空规划继续运行。
5. 新建对话和回复超时配置在真实适配器调用中生效。
6. 状态、审计和普通日志中不存在 Cookie、令牌、API key、完整页面 HTML或绝对任务路径。
7. 原有后端回归测试、静态界面测试和新增规划测试全部通过。
8. Python 语法检查和可用环境中的 JavaScript 语法检查通过。
9. 根目录 `server.js` 及其未提交改动保持不变。

## 本轮不包含

- LangGraph 节点、checkpoint、中断或恢复；
- 多规划器优先级链和运行时动态重排；
- ChatGPT 执行联网检索、正文写作、PPT/Word 生成或审核；
- 商业专利数据库自动登录；
- 浏览器 Cookie、令牌或 profile 的读取、迁移和持久化；
- React 设置界面重构；
- 根目录检索/PPT 应用的并行搜索改造。

## 后续迁移方向

未来接入 LangGraph 时，Planner Service 可以作为 `analyze_request` 节点内部的执行服务继续使用。规划契约、回退审计和文件格式保持不变，LangGraph 只接管节点调度、checkpoint 和人工审批，不重新实现浏览器交互与规划校验。
