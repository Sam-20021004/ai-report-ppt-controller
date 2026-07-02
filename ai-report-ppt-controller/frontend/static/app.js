const DRAFT_KEY = "ai-report-controller:draft-v2";
const RECENT_KEY = "ai-report-controller:recent-v2";

const examples = {
  patent: {
    title: "GaN功率器件专利态势分析",
    task_type: "ppt_word",
    domain: "知识产权",
    audience: "企业技术部门",
    language: "中文",
    ppt_pages: "20",
    word_target_words: "8000",
    keywords: "GaN, 氮化镓, 功率器件, 专利布局",
    region: "全球，中国，美国，欧洲，日本",
    time_range: "2018-2026",
    database_scope: "公开网络、专利数据库、论文数据库、产业报告",
    search_boundary: "聚焦GaN功率器件、射频器件、衬底材料、产业链企业、核心专利族和近年技术竞争格局。",
    user_outline: "1. 产业背景与技术路线\n2. 全球专利布局\n3. 重点企业竞争态势\n4. 风险与机会\n5. 行动建议",
    enable_patent_search: true,
    enable_paper_search: true,
    enable_industry_search: true
  },
  paper: {
    title: "具身智能最新论文分享PPT",
    task_type: "ppt",
    domain: "AI",
    audience: "科研组会",
    language: "中文",
    ppt_pages: "15",
    keywords: "embodied AI, robotics foundation model, manipulation",
    time_range: "近三年",
    database_scope: "论文数据库、预印本、开源项目",
    search_boundary: "优先关注高被引论文、顶会论文和可复现实验。",
    user_outline: "1. 研究背景\n2. 代表论文\n3. 方法比较\n4. 实验结果\n5. 讨论与展望",
    enable_paper_search: true
  },
  industry: {
    title: "AI算力产业链分析",
    task_type: "word",
    domain: "AI",
    audience: "投资人",
    language: "中文",
    word_target_words: "10000",
    keywords: "AI算力, GPU, ASIC, 数据中心, 产业链",
    region: "中国，美国，全球",
    time_range: "近五年",
    database_scope: "产业报告、上市公司公告、新闻资讯",
    search_boundary: "关注上游芯片、服务器、数据中心、云服务和应用侧需求。",
    user_outline: "1. 市场背景\n2. 产业链结构\n3. 重点公司\n4. 供需与价格\n5. 风险判断",
    enable_industry_search: true
  },
  fto: {
    title: "目标产品FTO风险分析",
    task_type: "research_only",
    domain: "知识产权",
    audience: "企业法务与研发团队",
    language: "中文",
    keywords: "产品名称, 核心技术特征, FTO, 侵权风险",
    region: "中国，美国，欧洲",
    time_range: "有效专利",
    database_scope: "专利数据库、法律状态、同族专利",
    search_boundary: "围绕核心技术特征拆解检索式，重点关注权利要求覆盖范围和法律状态。",
    user_outline: "1. 技术特征拆解\n2. 检索策略\n3. 高风险专利\n4. 规避建议",
    enable_patent_search: true
  }
};

const state = {
  taskId: null,
  health: null,
  checks: {},
};

const form = document.querySelector("#task-form");
const workflow = document.querySelector("#workflow");
const emptyWorkflow = document.querySelector("#empty-workflow");
const statusEl = document.querySelector("#task-status");
const systemLog = document.querySelector("#system-log");
const agentOutput = document.querySelector("#agent-output");
const chromeOutput = document.querySelector("#chrome-output");
const searchOutput = document.querySelector("#search-output");
const connectionStatus = document.querySelector("#connection-status");
const preflightList = document.querySelector("#preflight-list");
const currentTask = document.querySelector("#current-task");
const taskActions = document.querySelector("#task-actions");
const fileList = document.querySelector("#file-list");
const toolRegistry = document.querySelector("#tool-registry");
const topStatus = document.querySelector("#top-status");
const toast = document.querySelector("#toast");
const formError = document.querySelector("#form-error");
const restoreDraftButton = document.querySelector("#restore-draft");
const rightRestoreDraftButton = document.querySelector("#right-restore-draft");
const recentTasks = document.querySelector("#recent-tasks");

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

document.querySelector("#check-all").addEventListener("click", checkAll);
document.querySelector("#check-chrome").addEventListener("click", checkChrome);
document.querySelector("#create-task").addEventListener("click", createTask);
document.querySelector("#run-task").addEventListener("click", runTask);
document.querySelector("#refresh-task").addEventListener("click", refreshTask);
document.querySelector("#pause-task").addEventListener("click", () => taskAction("pause"));
document.querySelector("#cancel-task").addEventListener("click", () => taskAction("cancel"));
document.querySelector("#rerun-step").addEventListener("click", () => taskAction("rerun-step", { step_index: 1 }));
document.querySelector("#load-config").addEventListener("click", loadConfig);
document.querySelector("#top-settings").addEventListener("click", loadConfig);
document.querySelector("#top-help").addEventListener("click", () => showToast("先填写左侧任务目标，或点击加载示例任务；草稿和示例不会自动污染新任务。"));
document.querySelector("#upload-ppt").addEventListener("click", () => uploadFile("ppt-template", "/api/upload/template/ppt"));
document.querySelector("#upload-word").addEventListener("click", () => uploadFile("word-template", "/api/upload/template/word"));
document.querySelector("#save-draft").addEventListener("click", saveDraft);
document.querySelector("#clear-form").addEventListener("click", clearForm);
document.querySelector("#new-blank").addEventListener("click", clearForm);
document.querySelector("#right-new-task").addEventListener("click", clearForm);
document.querySelector("#right-save-draft").addEventListener("click", saveDraft);
document.querySelector("#right-load-example").addEventListener("click", () => loadExample("patent"));
document.querySelector("#load-example").addEventListener("click", () => loadExample("patent"));
restoreDraftButton.addEventListener("click", restoreDraft);
rightRestoreDraftButton.addEventListener("click", restoreDraft);
document.querySelector("#task-type").addEventListener("change", updateOutputVisibility);
form.addEventListener("input", () => {
  syncFollowerTitles();
  renderPreflight();
});
document.querySelectorAll(".example-card").forEach((button) => {
  button.addEventListener("click", () => loadExample(button.dataset.example));
});
document.querySelectorAll("[name='ppt_topic'], [name='word_topic']").forEach((input) => {
  input.addEventListener("input", () => {
    input.dataset.userEdited = input.value ? "true" : "";
  });
});

init();

async function init() {
  renderEmptyWorkflow();
  updateOutputVisibility();
  updateDraftButton();
  renderRecentTasks();
  renderPreflight();
  await loadHealth();
  renderRegistry();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.error || "请求失败");
  }
  return data;
}

function getPayload() {
  const data = new FormData(form);
  const bool = (name) => data.get(name) === "on";
  const title = String(data.get("title") || "").trim();
  const pptTopic = String(data.get("ppt_topic") || "").trim() || title;
  const wordTopic = String(data.get("word_topic") || "").trim() || title;
  return {
    title,
    task_type: data.get("task_type"),
    domain: trimValue(data.get("domain")),
    audience: trimValue(data.get("audience")),
    language: data.get("language"),
    ppt_topic: pptTopic,
    ppt_pages: numberOrNull(data.get("ppt_pages")),
    word_topic: wordTopic,
    word_target_words: numberOrNull(data.get("word_target_words")),
    search_boundary: trimValue(data.get("search_boundary")),
    keywords: trimValue(data.get("keywords")),
    region: trimValue(data.get("region")),
    time_range: trimValue(data.get("time_range")),
    database_scope: trimValue(data.get("database_scope")),
    user_outline: trimValue(data.get("user_outline")),
    main_agent: data.get("main_agent"),
    review_agent: data.get("review_agent"),
    loop_rounds: numberOrNull(data.get("loop_rounds")) || 1,
    enable_web_search: bool("enable_web_search"),
    enable_patent_search: bool("enable_patent_search"),
    enable_paper_search: bool("enable_paper_search"),
    enable_industry_search: bool("enable_industry_search"),
    enable_cross_review: bool("enable_cross_review"),
    enable_fact_check: bool("enable_fact_check"),
    enable_format_check: bool("enable_format_check"),
    enable_professional_review: bool("enable_professional_review"),
  };
}

function validateRequired() {
  const title = String(new FormData(form).get("title") || "").trim();
  if (!title) {
    showFormError("请先填写任务标题。");
    document.querySelector("[name='title']").focus();
    return false;
  }
  showFormError("");
  return true;
}

async function loadHealth() {
  state.health = await api("/api/health");
  logSystem("健康检查完成", state.health);
  renderConnections();
}

async function loadConfig() {
  const config = await api("/api/config");
  logSystem("当前配置", config);
  setTab("system");
  showToast("配置已读取。");
}

async function checkAll() {
  setBusy("#check-all", true);
  try {
    const [codex, hermes, chrome] = await Promise.all([
      api("/api/check/codex", { method: "POST", body: "{}" }),
      api("/api/check/hermes", { method: "POST", body: "{}" }),
      api("/api/check/chrome", { method: "POST", body: "{}" }),
    ]);
    state.checks = { codex, hermes, chrome };
    agentOutput.textContent = JSON.stringify({ codex, hermes }, null, 2);
    chromeOutput.textContent = JSON.stringify(chrome, null, 2);
    renderConnections();
    renderRegistry();
    showToast("连接检测完成。");
  } finally {
    setBusy("#check-all", false);
  }
}

async function checkChrome() {
  const chrome = await api("/api/check/chrome", { method: "POST", body: "{}" });
  state.checks.chrome = chrome;
  chromeOutput.textContent = JSON.stringify(chrome, null, 2);
  renderConnections();
  setTab("chrome");
}

async function createTask() {
  if (!validateRequired()) return null;
  setBusy("#create-task", true);
  try {
    const payload = getPayload();
    const record = await api("/api/task/create", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.taskId = record.task_id;
    renderTask(record);
    rememberTask(record);
    setTab("workflow");
    showToast("任务已创建。");
    return record;
  } finally {
    setBusy("#create-task", false);
  }
}

async function runTask() {
  if (!state.taskId) {
    const created = await createTask();
    if (!created) return;
  }
  setBusy("#run-task", true);
  try {
    const record = await api(`/api/task/${state.taskId}/run`, { method: "POST", body: "{}" });
    renderTask(record);
    logSystem("工作流运行完成", record);
    showToast("工作流已运行。");
  } finally {
    setBusy("#run-task", false);
  }
}

async function refreshTask() {
  if (!state.taskId) return showToast("尚未创建任务。");
  const record = await api(`/api/task/${state.taskId}`);
  renderTask(record);
  await loadFiles();
}

async function taskAction(action, payload = {}) {
  if (!state.taskId) return showToast("尚未创建任务。");
  const record = await api(`/api/task/${state.taskId}/${action}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderTask(record);
}

async function loadFiles() {
  if (!state.taskId) return;
  const data = await api(`/api/task/${state.taskId}/files`);
  renderFiles(data.files || []);
}

async function uploadFile(inputId, endpoint) {
  const input = document.querySelector(`#${inputId}`);
  if (!input.files.length) return showToast("请先选择文件。");
  const body = new FormData();
  body.append("file", input.files[0]);
  if (state.taskId) body.append("task_id", state.taskId);
  const data = await api(endpoint, { method: "POST", body });
  logSystem("上传完成", data);
  showToast("文件已上传。");
}

function saveDraft() {
  localStorage.setItem(DRAFT_KEY, JSON.stringify(getPayload()));
  updateDraftButton();
  showToast("草稿已保存。");
}

function restoreDraft() {
  const raw = localStorage.getItem(DRAFT_KEY);
  if (!raw) return showToast("没有可恢复的草稿。");
  fillForm(JSON.parse(raw));
  showToast("已恢复上次草稿。");
}

function clearForm() {
  form.reset();
  state.taskId = null;
  document.querySelectorAll("[name='ppt_topic'], [name='word_topic']").forEach((input) => {
    input.dataset.userEdited = "";
    input.value = "";
  });
  document.querySelectorAll("details").forEach((details) => {
    details.open = false;
  });
  document.querySelectorAll("input[type='file']").forEach((input) => {
    input.value = "";
  });
  showFormError("");
  currentTask.textContent = "暂无任务";
  taskActions.classList.add("hidden");
  fileList.textContent = "暂无生成文件";
  searchOutput.textContent = "运行工作流后显示检索计划或检索结果。";
  agentOutput.textContent = "等待连接检测或任务运行。";
  renderEmptyWorkflow();
  renderPreflight();
  updateOutputVisibility();
  setTab("workflow");
  showToast("已恢复为空白新建任务。");
}

function loadExample(name) {
  const example = examples[name] || examples.patent;
  fillForm(example);
  setTab("workflow");
  showToast("示例任务已填入表单。");
}

function fillForm(values) {
  clearWithoutToast();
  for (const [key, value] of Object.entries(values)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
    } else {
      field.value = value ?? "";
    }
  }
  syncFollowerTitles();
  updateOutputVisibility();
  renderPreflight();
}

function clearWithoutToast() {
  form.reset();
  state.taskId = null;
  document.querySelectorAll("input[type='file']").forEach((input) => {
    input.value = "";
  });
  document.querySelectorAll("[name='ppt_topic'], [name='word_topic']").forEach((input) => {
    input.dataset.userEdited = "";
    input.value = "";
  });
  showFormError("");
  currentTask.textContent = "暂无任务";
  taskActions.classList.add("hidden");
  fileList.textContent = "暂无生成文件";
  renderEmptyWorkflow();
}

function renderTask(record) {
  state.taskId = record.task_id;
  emptyWorkflow.classList.add("hidden");
  statusEl.textContent = `${record.status} | ${record.task_id}`;
  currentTask.textContent = `${record.request.title} (${record.task_id})`;
  taskActions.classList.remove("hidden");
  workflow.innerHTML = "";
  record.steps.forEach((step) => {
    const row = document.createElement("article");
    row.className = "step-row";
    row.innerHTML = `
      <div class="step-no">${step.index}</div>
      <strong>${escapeHtml(step.step_name)}</strong>
      <span>${escapeHtml(step.agent)}</span>
      <span class="step-summary">${escapeHtml(step.output_summary || step.error || "等待中")}</span>
      <span class="badge ${escapeHtml(step.status)}">${statusText(step.status)}</span>
    `;
    workflow.appendChild(row);
  });
  searchOutput.textContent = JSON.stringify({
    phase2_outputs_summary: record.phase2_outputs_summary || {},
    phase2_errors: record.phase2_errors || [],
    research_step: record.steps[2]?.output || { status: "pending" },
  }, null, 2);
  loadFiles();
}

function renderEmptyWorkflow() {
  emptyWorkflow.classList.remove("hidden");
  statusEl.textContent = "当前没有运行中的任务";
  workflow.innerHTML = "";
}

function renderConnections() {
  const items = [
    ["Backend", state.health?.ok, state.health?.phase || "unknown"],
    ["Codex", state.checks.codex?.ok, state.checks.codex?.status || "未检测"],
    ["Hermes", state.checks.hermes?.ok, state.checks.hermes?.status || "未检测"],
    ["Chrome", state.checks.chrome?.ok, state.checks.chrome?.status || "未检测"],
    ["输出目录", state.health?.storage?.writable, state.health?.storage?.writable ? "可写" : "未知"],
  ];
  connectionStatus.innerHTML = items.map(([name, ok, status]) => `
    <div class="status-item"><strong>${name}</strong><span class="badge ${ok ? "success" : "waiting"}">${escapeHtml(status)}</span></div>
  `).join("");
  topStatus.innerHTML = items.slice(0, 4).map(([name, ok, status]) => `
    <span class="${ok ? "ok" : "idle"}">${escapeHtml(name)} · ${escapeHtml(status)}</span>
  `).join("");
}

function renderPreflight() {
  const payload = getPayload();
  const checks = [
    ["任务标题", Boolean(payload.title), payload.title ? "已填写" : "未填写"],
    ["输出类型", Boolean(payload.task_type), payload.task_type || "未选择"],
    ["检索关键词", Boolean(payload.keywords), payload.keywords ? "已填写" : "为空"],
    ["PPT模板", Boolean(document.querySelector("#ppt-template").files.length), "可选"],
    ["Word模板", Boolean(document.querySelector("#word-template").files.length), "可选"],
    ["输出目录", Boolean(state.health?.storage?.writable), state.health?.storage?.writable ? "可写" : "待检测"],
  ];
  preflightList.innerHTML = checks.map(([name, ok, status]) => `
    <div class="status-item"><strong>${ok ? "●" : "○"} ${escapeHtml(name)}</strong><span>${escapeHtml(status)}</span></div>
  `).join("");
}

function renderRegistry() {
  const rows = [
    ["Task Manager", "任务创建/日志保存"],
    ["Codex Connector", state.checks.codex?.status || "Mock/CLI Adapter"],
    ["Hermes Connector", state.checks.hermes?.status || "Mock/API Adapter"],
    ["Chrome CDP", state.checks.chrome?.status || "9222 /json 检测"],
    ["Template Manager", "PPT/Word/材料上传"],
    ["Remote Access Auth", "本机模式默认开启，远程需 token"],
  ];
  toolRegistry.innerHTML = rows.map(([name, status]) => `<div class="registry-item"><strong>${name}</strong><span>${escapeHtml(status)}</span></div>`).join("");
}

function renderFiles(files) {
  if (!files.length) {
    fileList.textContent = "暂无生成文件";
    return;
  }
  fileList.innerHTML = files.map((file) => `
    <div class="file-item ${file.is_phase2_artifact ? "phase2-file" : ""}">
      <div class="file-main">
        <a href="/api/download/${escapeAttr(file.file_id)}">${escapeHtml(file.file_name)}</a>
        <span class="file-meta">${escapeHtml(file.description || file.relative_path || file.file_type || "")}</span>
      </div>
      <span>${Math.ceil(file.size / 1024)} KB</span>
    </div>
  `).join("");
}

function rememberTask(record) {
  const raw = localStorage.getItem(RECENT_KEY);
  const existing = raw ? JSON.parse(raw) : [];
  const next = [
    { task_id: record.task_id, title: record.request.title, status: record.status },
    ...existing.filter((item) => item.task_id !== record.task_id),
  ].slice(0, 5);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  renderRecentTasks();
}

function renderRecentTasks() {
  const raw = localStorage.getItem(RECENT_KEY);
  const tasks = raw ? JSON.parse(raw) : [];
  if (!tasks.length) {
    recentTasks.textContent = "暂无最近任务";
    return;
  }
  recentTasks.innerHTML = tasks.map((task) => `
    <div class="recent-item"><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.status)} · ${escapeHtml(task.task_id)}</span></div>
  `).join("");
}

function updateDraftButton() {
  const hasDraft = Boolean(localStorage.getItem(DRAFT_KEY));
  restoreDraftButton.classList.toggle("hidden", !hasDraft);
  rightRestoreDraftButton.classList.toggle("hidden", !hasDraft);
}

function syncFollowerTitles() {
  const title = form.elements.title.value.trim();
  ["ppt_topic", "word_topic"].forEach((name) => {
    const input = form.elements[name];
    if (document.activeElement === input) return;
    if (!input.dataset.userEdited) {
      input.value = title;
    }
  });
}

function updateOutputVisibility() {
  const type = form.elements.task_type.value;
  document.querySelectorAll(".ppt-only").forEach((el) => {
    el.classList.toggle("hidden", !["ppt", "ppt_word"].includes(type));
  });
  document.querySelectorAll(".word-only").forEach((el) => {
    el.classList.toggle("hidden", !["word", "ppt_word"].includes(type));
  });
}

function logSystem(title, value) {
  systemLog.textContent = `${title}\n${JSON.stringify(value, null, 2)}`;
}

function setTab(name) {
  document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === name));
}

function setBusy(selector, busy) {
  const button = document.querySelector(selector);
  if (button) button.disabled = busy;
}

function showFormError(message) {
  formError.textContent = message;
  formError.classList.toggle("hidden", !message);
}

function statusText(status) {
  return {
    waiting: "等待",
    running: "运行",
    success: "成功",
    failed: "失败",
    needs_review: "需确认",
    paused: "暂停",
    cancelled: "取消",
    skipped: "跳过",
    done: "完成",
  }[status] || status;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2600);
}

function trimValue(value) {
  return String(value || "").trim();
}

function numberOrNull(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return String(value ?? "").split("/").map(encodeURIComponent).join("/");
}
