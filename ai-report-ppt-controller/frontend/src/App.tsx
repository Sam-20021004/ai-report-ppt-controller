import { useState } from "react";
import { api } from "./api/client";
import { TaskInputPanel, type TaskFormState } from "./components/TaskInputPanel";
import { WorkflowTimeline } from "./components/WorkflowTimeline";
import { ConnectionStatusCard } from "./components/ConnectionStatusCard";
import { OutputFileList } from "./components/OutputFileList";
import type { TaskRecord } from "./store/types";
import "./styles/app.css";

const DRAFT_KEY = "ai-report-controller:react-draft-v2";

function emptyForm(): TaskFormState {
  return {
    title: "",
    task_type: "ppt",
    language: "中文",
    domain: "",
    audience: "",
    ppt_topic: "",
    ppt_pages: "",
    word_topic: "",
    word_target_words: "",
    keywords: "",
    region: "",
    time_range: "",
    database_scope: "",
    search_boundary: "",
    user_outline: "",
    main_agent: "auto",
    review_agent: "auto",
    loop_rounds: "1",
    enable_web_search: true,
    enable_patent_search: false,
    enable_paper_search: false,
    enable_industry_search: true,
    enable_cross_review: true,
    enable_fact_check: true,
    enable_format_check: true,
    enable_professional_review: true
  };
}

const exampleTask: TaskFormState = {
  ...emptyForm(),
  title: "GaN功率器件专利态势分析",
  task_type: "ppt_word",
  domain: "知识产权",
  audience: "企业技术部门",
  ppt_pages: "20",
  word_target_words: "8000",
  keywords: "GaN, 氮化镓, 功率器件, 专利布局",
  region: "全球，中国，美国，欧洲，日本",
  time_range: "2018-2026",
  database_scope: "公开网络、专利数据库、论文数据库、产业报告",
  search_boundary: "聚焦GaN功率器件、射频器件、衬底材料、产业链企业、核心专利族和近年技术竞争格局。",
  user_outline: "1. 产业背景与技术路线\n2. 全球专利布局\n3. 重点企业竞争态势\n4. 风险与机会\n5. 行动建议",
  enable_patent_search: true,
  enable_paper_search: true
};

export default function App() {
  const [formState, setFormState] = useState<TaskFormState>(() => emptyForm());
  const [task, setTask] = useState<TaskRecord | null>(null);
  const [checks, setChecks] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasDraft, setHasDraft] = useState(() => Boolean(localStorage.getItem(DRAFT_KEY)));
  const [activeTab, setActiveTab] = useState("workflow");

  function updateForm(field: keyof TaskFormState, nextValue: string | boolean) {
    setFormState((previous) => {
      if (field === "title" && typeof nextValue === "string") {
        const pptWasFollowing = !previous.ppt_topic || previous.ppt_topic === previous.title;
        const wordWasFollowing = !previous.word_topic || previous.word_topic === previous.title;
        return {
          ...previous,
          title: nextValue,
          ppt_topic: pptWasFollowing ? nextValue : previous.ppt_topic,
          word_topic: wordWasFollowing ? nextValue : previous.word_topic
        };
      }
      return { ...previous, [field]: nextValue };
    });
  }

  function buildPayload() {
    return {
      ...formState,
      title: formState.title.trim(),
      ppt_topic: formState.ppt_topic.trim() || formState.title.trim(),
      word_topic: formState.word_topic.trim() || formState.title.trim(),
      ppt_pages: formState.ppt_pages ? Number(formState.ppt_pages) : null,
      word_target_words: formState.word_target_words ? Number(formState.word_target_words) : null,
      loop_rounds: formState.loop_rounds ? Number(formState.loop_rounds) : 1
    };
  }

  async function createTaskRecord() {
    const payload = buildPayload();
    if (!payload.title) {
      setError("请先填写任务标题。");
      return null;
    }
    setBusy(true);
    setError("");
    try {
      const record = await api<TaskRecord>("/api/task/create", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setTask(record);
      return record;
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建任务失败");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function createTask() {
    await createTaskRecord();
  }

  async function runTask() {
    const baseTask = task || await createTaskRecord();
    if (!baseTask) return;
    setBusy(true);
    setError("");
    try {
      const record = await api<TaskRecord>(`/api/task/${baseTask.task_id}/run`, {
        method: "POST",
        body: "{}"
      });
      setTask(record);
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function checkAgents() {
    setBusy(true);
    setError("");
    try {
      const [hermes, codex, chrome] = await Promise.all([
        api("/api/check/hermes", { method: "POST", body: "{}" }),
        api("/api/check/codex", { method: "POST", body: "{}" }),
        api("/api/check/chrome", { method: "POST", body: "{}" })
      ]);
      setChecks({ hermes, codex, chrome });
    } catch (err) {
      setError(err instanceof Error ? err.message : "连接检测失败");
    } finally {
      setBusy(false);
    }
  }

  function clearForm() {
    setFormState(emptyForm());
    setTask(null);
    setError("");
  }

  function saveDraft() {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(formState));
    setHasDraft(true);
  }

  function restoreDraft() {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return;
    setFormState({ ...emptyForm(), ...JSON.parse(raw) });
  }

  function loadExample() {
    setFormState(exampleTask);
    setError("");
  }

  const tabs = [
    ["workflow", "工作流"],
    ["search", "检索结果"],
    ["agent", "Agent 输出"],
    ["ppt", "PPT 输出"],
    ["word", "Word 输出"],
    ["chrome", "Chrome CLI"],
    ["system", "系统日志"],
    ["tools", "工具注册表"]
  ];

  return (
    <>
      <header className="topbar">
        <div>
          <h1>AI Report & PPT Agent Controller</h1>
          <p>本机 Agent 控制台 · Local Mode</p>
        </div>
        <div className="topbar-side">
          <div className="top-status">
            <span className="ok">Backend · Phase 1</span>
            <span>Codex · 未检测</span>
            <span>Hermes · Mock</span>
            <span>Chrome CDP · 未连接</span>
            <span className="ok">输出目录 · 可写</span>
          </div>
          <div className="top-actions">
            <button type="button" onClick={checkAgents}>设置</button>
            <button type="button" onClick={() => setError("先填写左侧任务目标，或主动加载示例任务。")}>帮助</button>
          </div>
        </div>
      </header>

      <main className="app-shell">
        <TaskInputPanel
          value={formState}
          onChange={updateForm}
          onCreate={createTask}
          onRun={runTask}
          onClear={clearForm}
          onSaveDraft={saveDraft}
        />

        <section className="center-panel">
          <nav className="tabs">
            {tabs.map(([key, label]) => (
              <button key={key} className={`tab ${activeTab === key ? "active" : ""}`} type="button" onClick={() => setActiveTab(key)}>
                {label}
              </button>
            ))}
          </nav>

          <section className={`tab-panel ${activeTab === "workflow" ? "active" : ""}`}>
            <div className="panel-head">
              <h2>工作流控制台</h2>
              <span>{task ? `任务 ${task.task_id} · ${task.status}` : "当前没有运行中的任务"}</span>
            </div>
            {error ? <p className="error-text">{error}</p> : null}
            {!task ? (
              <div className="empty-workflow">
                <h3>当前没有运行中的任务</h3>
                <p>请在左侧填写任务目标，或从下方选择示例任务。示例不会自动填入表单。</p>
                <div className="button-row left">
                  <button type="button" onClick={clearForm}>新建空白任务</button>
                  <button className="secondary" type="button" onClick={loadExample}>加载示例任务</button>
                  {hasDraft ? <button className="secondary" type="button" onClick={restoreDraft}>恢复上次草稿</button> : null}
                </div>
              </div>
            ) : (
              <WorkflowTimeline steps={task.steps} />
            )}
            <section className="workflow-preview">
              <h3>标准 Multi-agent Loop</h3>
              <ol>
                <li>任务解析</li>
                <li>Hermes 检索规划</li>
                <li>Chrome CLI 联网搜索</li>
                <li>Codex 生成大纲</li>
                <li>Hermes 专业审核</li>
                <li>Codex 修改</li>
                <li>PPT / Word 文件生成</li>
                <li>最终质检</li>
              </ol>
            </section>
            <section className="example-zone">
              <h3>示例任务</h3>
              <div className="example-grid">
                <button className="example-card" type="button" onClick={loadExample}>专利态势分析</button>
                <button className="example-card" type="button" onClick={loadExample}>论文分享 PPT</button>
                <button className="example-card" type="button" onClick={loadExample}>产业链分析</button>
                <button className="example-card" type="button" onClick={loadExample}>FTO 风险分析</button>
              </div>
            </section>
            <section className="recent-zone">
              <h3>最近任务</h3>
              <div className="recent-list">暂无最近任务</div>
            </section>
          </section>

          <section className={`tab-panel ${activeTab === "search" ? "active" : ""}`}>
            <div className="panel-head"><h2>检索结果</h2><span>sources.json</span></div>
            <pre className="terminal">运行工作流后显示检索计划或检索结果。</pre>
          </section>
          <section className={`tab-panel ${activeTab === "agent" ? "active" : ""}`}>
            <div className="panel-head"><h2>Agent 输出</h2><span>Codex / Hermes</span></div>
            <pre className="terminal tall">暂无输出。</pre>
          </section>
          <section className={`tab-panel ${activeTab === "ppt" ? "active" : ""}`}>
            <div className="panel-head"><h2>PPT 输出</h2><span>Phase 3</span></div>
            <pre className="terminal tall">运行到文件生成阶段后显示 PPTX 输出。</pre>
          </section>
          <section className={`tab-panel ${activeTab === "word" ? "active" : ""}`}>
            <div className="panel-head"><h2>Word 输出</h2><span>Phase 3</span></div>
            <pre className="terminal tall">运行到文件生成阶段后显示 DOCX 输出。</pre>
          </section>
          <section className={`tab-panel ${activeTab === "chrome" ? "active" : ""}`}>
            <div className="panel-head"><h2>Chrome CLI / CDP</h2><button type="button" onClick={checkAgents}>检测 Chrome</button></div>
            <pre className="terminal compact">chrome.exe --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="D:\chrome-debug-profile"</pre>
          </section>
          <section className={`tab-panel ${activeTab === "system" ? "active" : ""}`}>
            <div className="panel-head"><h2>系统日志</h2><span>轮询 fallback</span></div>
            <pre className="terminal tall">APP 已加载。</pre>
          </section>
          <section className={`tab-panel ${activeTab === "tools" ? "active" : ""}`}>
            <div className="panel-head"><h2>工具注册表</h2><span>白名单封装</span></div>
            <div className="registry">等待后端工具注册表。</div>
          </section>
        </section>

        <aside className="right-panel">
          <ConnectionStatusCard checks={checks} />
          <section className="status-card">
            <h2>运行前检查</h2>
            <div className="status-list">
              <div className="status-item"><span>任务标题</span><span className={`badge ${formState.title.trim() ? "success" : "failed"}`}>{formState.title.trim() ? "已填写" : "未填写"}</span></div>
              <div className="status-item"><span>输出类型</span><span className="badge success">{formState.task_type}</span></div>
              <div className="status-item"><span>关键词</span><span className={`badge ${formState.keywords.trim() ? "success" : "warning"}`}>{formState.keywords.trim() ? "已填写" : "可选"}</span></div>
              <div className="status-item"><span>Chrome</span><span className="badge warning">未连接</span></div>
            </div>
          </section>
          <section className="status-card">
            <h2>当前任务</h2>
            <p>{task ? `${task.task_id} · ${task.status}` : "暂无任务"}</p>
            {task ? (
              <div className="button-grid">
                <button type="button" onClick={runTask}>重跑失败步骤</button>
                <button type="button" disabled={busy}>刷新</button>
              </div>
            ) : null}
          </section>
          <OutputFileList files={task?.generated_files ?? []} />
          <section className="status-card">
            <h2>快捷操作</h2>
            <div className="button-grid">
              <button type="button" onClick={clearForm}>新建空白任务</button>
              <button type="button" onClick={saveDraft}>保存草稿</button>
              {hasDraft ? <button type="button" onClick={restoreDraft}>恢复上次草稿</button> : null}
              <button type="button" onClick={loadExample}>加载示例任务</button>
              <button type="button" onClick={checkAgents}>系统设置</button>
            </div>
          </section>
        </aside>
      </main>
    </>
  );
}
