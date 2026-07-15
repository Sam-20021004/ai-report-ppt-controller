# AI Agent 汇报页版式精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单页 PPT 调整为左侧精简、中部简化、右侧真实 APP 界面显著放大的集团汇报页。

**Architecture:** 继续使用现有 JavaScript ES Module 生成器和 `@oai/artifact-tool`，不引入新模板或新依赖。通过修改固定坐标、缩减文本和重构原生形状连接关系，生成一个保持 1 页、16:9、可编辑的新版 PPT，并用渲染预览和边界检查验证。

**Tech Stack:** JavaScript ES Module、`@oai/artifact-tool`、PowerPoint 原生形状与连接线、演示文稿 QA 工具。

## Global Constraints

- 最终严格为 1 页、16:9。
- Logo 和真实 APP 截图保持原始比例，不修改截图业务内容。
- 中部仅保留任务入口、Multi-Agent 编排、Hermes、Codex、审核交付和一条反馈回路。
- Hermes 表述为数据收集、来源整理和资料归纳；Codex 表述为任务规划、结构设计和报告/PPT 生成。
- 规划能力继续使用“拟升级、下一阶段、规划”等措辞，不表述为已部署完成。
- 架构节点、连接线和文字必须为 PowerPoint 原生可编辑对象。

---

### Task 1: 重构页面比例与内容密度

**Files:**
- Modify: `outputs/generate_ai_agent_slide.mjs`

**Interfaces:**
- Consumes: `addBox(...)`、`addText(...)`、`addNode(...)` 和现有素材路径。
- Produces: 更新后的 `main()` 页面布局，供 Task 2 直接运行生成。

- [ ] **Step 1: 记录现有布局的视觉基线**

Run:

```powershell
Get-Item 'outputs/新微_AI报告生成Agent工具开发构想_preview.png' | Select-Object Name,Length,LastWriteTime
```

Expected: 返回现有 1600×900 预览文件信息。

- [ ] **Step 2: 压缩左侧信息区**

将左侧宽度压缩至约 250–270 px，三项内容分别改为一句：

```js
const leftCards = [
  ["已有基础", "已形成任务配置、联网检索与报告输出的 MVP 流程。"],
  ["升级方向", "下一阶段引入 Multi-Agent 编排与质量闭环。"],
  ["建设目标", "沉淀可复用、可审计的集团智能工作能力。"],
];
```

Expected: 左侧不再出现长段落，并释放中右区域宽度。

- [ ] **Step 3: 将中部架构简化为两类核心执行能力**

用原生形状构建以下节点，不再保留六个专业 Agent 横向排列：

```js
const entry = addNode(slide, "entry", "任务入口", "需求 · 资料 · 模板", x, y, w, h, C.mist, C.line);
const orch = addNode(slide, "orchestrator", "Multi-Agent 编排中枢", "任务理解 · 路由 · 状态管理", x, y, w, h, C.navy, C.navy, C.white);
const hermes = addNode(slide, "hermes", "Hermes｜数据收集整理", "联网检索 · 来源整理 · 资料归纳", x, y, w, h, C.pale, "#9CC4E1");
const codex = addNode(slide, "codex", "Codex｜规划与报告生成", "任务规划 · 结构设计 · 报告 / PPT 生成", x, y, w, h, "#EEF3F8", "#90AAC0");
const delivery = addNode(slide, "delivery", "审核与交付", "来源核验 · 逻辑检查 · 多格式输出", x, y, w, h, "#E9F5F0", "#8AC5AA", C.green);
```

使用自上而下的主流程箭头，并添加一条从“审核与交付”返回“Multi-Agent 编排中枢”的虚线反馈箭头。

Expected: 中部流程在整页预览中可一眼读懂 Codex 与 Hermes 的职责分工。

- [ ] **Step 4: 放大右侧真实 APP 界面**

将截图区域扩大至页面约 42%–46% 宽度，并使用 `fit: "contain"`：

```js
slide.images.add({
  blob: await bytes(path.join(ASSETS, "app-current.png")),
  contentType: "image/png",
  alt: "AI Report & PPT Agent Controller 当前界面截图",
  fit: "contain",
  position: { left: rightX, top: 160, width: rightW, height: 430 },
  geometry: "roundRect",
  borderRadius: "rounded-lg",
});
```

截图下方仅保留三个短标签：“任务配置”“协同工作流”“多格式输出”。

Expected: 截图面积明显大于旧版，主界面主要分区在整页预览中可辨认。

- [ ] **Step 5: 压缩底部阶段小结并检查措辞边界**

使用以下结论式文案：

```text
当前已完成 MVP 流程验证；下一阶段拟以 Multi-Agent 架构明确 Codex 与 Hermes 的专业分工，强化质量审核与成果交付，并纳入新微 AI 工具建设计划。
```

Expected: 同时保留已有基础、拟升级、纳入工作计划三层含义，不出现未经确认的部署结论。

### Task 2: 生成新版交付文件

**Files:**
- Modify: `outputs/新微_AI报告生成Agent工具开发构想.pptx`
- Modify: `outputs/新微_AI报告生成Agent工具开发构想_preview.png`
- Modify: `outputs/asset_notes.md`

**Interfaces:**
- Consumes: Task 1 更新后的 `outputs/generate_ai_agent_slide.mjs`。
- Produces: 最终 PPT、预览图和更新后的素材说明。

- [ ] **Step 1: 运行生成脚本**

Run:

```powershell
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'D:\codex-project\APP\outputs\generate_ai_agent_slide.mjs'
```

Expected: 命令退出码为 0，并更新 PPT 与 PNG 文件时间。

- [ ] **Step 2: 更新素材说明**

在 `outputs/asset_notes.md` 中补充：中部架构已按用户反馈精简为 Hermes 与 Codex 两类核心执行能力；真实 APP 截图已放大但未修改内容。

- [ ] **Step 3: 检查交付文件存在且非空**

Run:

```powershell
Get-Item 'outputs/新微_AI报告生成Agent工具开发构想.pptx','outputs/新微_AI报告生成Agent工具开发构想_preview.png','outputs/asset_notes.md','outputs/generate_ai_agent_slide.mjs' | Select-Object Name,Length
```

Expected: 四个文件均存在，长度大于 0。

### Task 3: 视觉与技术验收

**Files:**
- Test: `outputs/新微_AI报告生成Agent工具开发构想.pptx`
- Test: `outputs/新微_AI报告生成Agent工具开发构想_preview.png`

**Interfaces:**
- Consumes: Task 2 生成的最终文件。
- Produces: 通过的视觉检查与自动边界检查结果。

- [ ] **Step 1: 全尺寸查看预览图**

使用图像查看工具打开 `outputs/新微_AI报告生成Agent工具开发构想_preview.png`。

Expected: Logo 未变形；右侧截图明显放大；中部只有 Hermes、Codex 和审核交付核心结构；文字无截断或异常换行。

- [ ] **Step 2: 运行页面溢出检查**

Run:

```powershell
$env:HOME='C:\Users\27235'
& 'C:\Users\27235\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'D:\codex_wenj\plugins\cache\openai-primary-runtime\presentations\26.709.11516\skills\presentations\container_tools\slides_test.py' 'D:\codex-project\APP\outputs\新微_AI报告生成Agent工具开发构想.pptx'
```

Expected: `Test passed. No overflow detected.`

- [ ] **Step 3: 核验页数与比例**

读取 PPTX 包内 `ppt/presentation.xml` 和 `ppt/slides/slide1.xml`。

Expected: 仅有 1 张幻灯片；`sldSz` 宽高比为 16:9。

- [ ] **Step 4: 最终人工复核**

确认主流程箭头方向一致，虚线反馈回路不穿过节点文字，截图标签不遮挡界面，底部结论不与标签重叠。

Expected: 所有检查项通过后才交付。
