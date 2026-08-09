const DRAFT_KEY = "ai-report-controller:draft-v2";
const RECENT_KEY = "ai-report-controller:recent-v2";
const CURRENT_TASK_KEY = "ai_report_current_task_id";

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
  pollTimer: null,
  taskHistory: [],
};

const REVIEW_STATUS_LABELS = {
  unreviewed: "未复核",
  approved: "通过",
  rejected: "驳回",
  needs_followup: "待跟进",
};

const REVIEW_STATUS_OPTIONS = Object.keys(REVIEW_STATUS_LABELS);

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
let phase2Audit = document.querySelector("#phase2-audit");
const toolRegistry = document.querySelector("#tool-registry");
const topStatus = document.querySelector("#top-status");
const toast = document.querySelector("#toast");
const formError = document.querySelector("#form-error");
const restoreDraftButton = document.querySelector("#restore-draft");
const rightRestoreDraftButton = document.querySelector("#right-restore-draft");
const recentTasks = document.querySelector("#recent-tasks");
const plannerMode = document.querySelector("#planner-mode");
const chatgptMode = document.querySelector("#chatgpt-mode");
const chatgptUseNewChat = document.querySelector("#chatgpt-use-new-chat");
const chatgptReplyTimeout = document.querySelector("#chatgpt-reply-timeout");
const chatgptCheckResult = document.querySelector("#chatgpt-check-result");

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

document.querySelector("#check-all").addEventListener("click", checkAll);
document.querySelector("#check-chrome").addEventListener("click", checkChrome);
document.querySelector("#check-chatgpt").addEventListener("click", checkChatGPT);
document.querySelector("#save-planner-config").addEventListener("click", savePlannerConfig);
plannerMode.addEventListener("change", syncPlannerControls);
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
  syncPlannerControls();
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
  ensureAuditPanel();
  renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
  renderEmptyWorkflow();
  updateOutputVisibility();
  updateDraftButton();
  renderRecentTasks();
  renderPreflight();
  await loadHealth().catch((error) => {
    logSystem("Backend health check failed", { error: error.message });
    renderConnections();
  });
  renderRegistry();
  await loadTaskHistory();
  await restoreCurrentTaskOnReload();
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

async function restoreCurrentTaskOnReload() {
  const taskId = getRememberedCurrentTaskId();
  if (!taskId) return;
  try {
    const record = await openTaskById(taskId, { showSuccess: false });
    logSystem("Current task restored after reload", { task_id: record.task_id });
  } catch (error) {
    forgetCurrentTask();
    state.taskId = null;
    stopTaskPolling();
    renderEmptyWorkflow();
    renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
    logSystem("Current task restore skipped", { task_id: taskId, error: error.message });
  }
}

async function loadTaskHistory() {
  try {
    const data = await api("/api/tasks");
    state.taskHistory = normalizeTaskSummaries(data.tasks || []);
  } catch (error) {
    state.taskHistory = [];
    logSystem("历史任务列表加载失败", { error: error.message });
  }
  renderRecentTasks();
}

async function loadConfig() {
  const config = await api("/api/config");
  plannerMode.value = config.planner_mode === "chatgpt" ? "chatgpt" : "hermes";
  chatgptMode.value = config.chatgpt_mode === "cdp" ? "cdp" : "mock";
  chatgptUseNewChat.checked = config.chatgpt_use_new_chat !== false;
  chatgptReplyTimeout.value = String(config.chatgpt_reply_timeout_s || 600);
  syncPlannerControls();
  logSystem("当前配置", config);
  setTab("system");
  showToast("配置已读取。");
}

async function savePlannerConfig() {
  const timeout = Number(chatgptReplyTimeout.value);
  if (!Number.isInteger(timeout) || timeout < 30 || timeout > 1800) {
    showToast("ChatGPT 回复超时必须是 30–1800 秒的整数。");
    return;
  }
  setBusy("#save-planner-config", true);
  try {
    const payload = {
      planner_mode: plannerMode.value === "chatgpt" ? "chatgpt" : "hermes",
      chatgpt_mode: chatgptMode.value === "cdp" ? "cdp" : "mock",
      chatgpt_use_new_chat: Boolean(chatgptUseNewChat.checked),
      chatgpt_reply_timeout_s: timeout,
    };
    const config = await api("/api/config/update", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    logSystem("规划器配置已更新", config);
    syncPlannerControls();
    showToast("规划器设置已保存。");
  } finally {
    setBusy("#save-planner-config", false);
  }
}

async function checkAll() {
  setBusy("#check-all", true);
  try {
    const [codex, hermes, chrome, chatgpt] = await Promise.all([
      api("/api/check/codex", { method: "POST", body: "{}" }),
      api("/api/check/hermes", { method: "POST", body: "{}" }),
      api("/api/check/chrome", { method: "POST", body: "{}" }),
      api("/api/check/chatgpt", { method: "POST", body: "{}" }),
    ]);
    state.checks = { codex, hermes, chrome, chatgpt };
    agentOutput.textContent = JSON.stringify({ codex, hermes, chatgpt }, null, 2);
    chromeOutput.textContent = JSON.stringify(chrome, null, 2);
    chatgptCheckResult.textContent = `${chatgpt.status || "unknown"}: ${chatgpt.detail || ""}`;
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

async function checkChatGPT() {
  setBusy("#check-chatgpt", true);
  try {
    const chatgpt = await api("/api/check/chatgpt", { method: "POST", body: "{}" });
    state.checks.chatgpt = chatgpt;
    chatgptCheckResult.textContent = `${chatgpt.status || "unknown"}: ${chatgpt.detail || ""}`;
    logSystem("ChatGPT 连接检测", chatgpt);
    renderConnections();
    renderRegistry();
    setTab("system");
  } finally {
    setBusy("#check-chatgpt", false);
  }
}

function syncPlannerControls() {
  const enabled = plannerMode.value === "chatgpt";
  [chatgptMode, chatgptUseNewChat, chatgptReplyTimeout].forEach((control) => {
    control.disabled = !enabled;
  });
  document.querySelectorAll(".chatgpt-setting").forEach((field) => {
    field.classList.toggle("setting-disabled", !enabled);
  });
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
    rememberTask(record);
    startTaskPolling();
    logSystem("工作流已启动", record);
    showToast("任务已启动，状态将自动刷新。");
  } finally {
    setBusy("#run-task", false);
  }
}

async function refreshTask() {
  if (!state.taskId) return showToast("尚未创建任务。");
  const record = await api(`/api/task/${state.taskId}`);
  renderTask(record);
  rememberTask(record);
  await loadFiles();
}

async function openTaskById(taskId, options = {}) {
  const normalizedTaskId = String(taskId || "").trim();
  if (!normalizedTaskId) throw new Error("Task id is empty.");
  try {
    const record = await api(`/api/task/${encodeURIComponent(normalizedTaskId)}`);
    renderTask(record);
    rememberTask(record);
    setTab("workflow");
    if (options.showSuccess !== false) showToast("历史任务已打开。");
    return record;
  } catch (error) {
    forgetCurrentTask();
    if (!state.taskId) {
      renderEmptyWorkflow();
      renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
    }
    logSystem("历史任务打开失败", { task_id: normalizedTaskId, error: error.message });
    if (options.showError !== false) showToast(`历史任务打开失败：${error.message}`);
    throw error;
  }
}

async function openHistoryTask(taskId) {
  try {
    await openTaskById(taskId);
  } catch (error) {
    // Error is already logged and surfaced by openTaskById.
  }
}

function startTaskPolling() {
  if (state.pollTimer) return;
  state.pollTimer = window.setInterval(pollTaskStatus, 2000);
  pollTaskStatus();
}

function stopTaskPolling() {
  if (!state.pollTimer) return;
  window.clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function pollTaskStatus() {
  if (!state.taskId) {
    stopTaskPolling();
    return;
  }
  try {
    const record = await api(`/api/task/${state.taskId}`);
    renderTask(record);
    rememberTask(record);
    if (!isRunningStatus(record.status)) {
      stopTaskPolling();
      await loadFiles();
    }
  } catch (error) {
    stopTaskPolling();
    logSystem("任务状态轮询失败", { error: error.message });
    showToast("任务状态刷新失败，可手动刷新重试。");
  }
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

async function loadPhase2Audit() {
  if (!state.taskId) {
    renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
    return;
  }
  const data = await api(`/api/task/${state.taskId}/phase2/audit`);
  renderPhase2Audit(data);
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
  forgetCurrentTask();
  stopTaskPolling();
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
  renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
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
  forgetCurrentTask();
  stopTaskPolling();
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
  renderPhase2AuditUnavailable("运行研究任务后显示审计信息。");
  renderEmptyWorkflow();
}

function renderTask(record) {
  state.taskId = record.task_id;
  rememberCurrentTask(record.task_id);
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
  if (isRunningStatus(record.status)) {
    startTaskPolling();
  } else {
    stopTaskPolling();
  }
  loadFiles().catch((error) => logSystem("文件列表刷新失败", { error: error.message }));
  loadPhase2Audit().catch((error) => {
    renderPhase2AuditUnavailable("审计信息暂不可用。", [error.message]);
    logSystem("Phase 2 审计信息刷新失败", { error: error.message });
  });
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
    ["ChatGPT", state.checks.chatgpt?.ok, state.checks.chatgpt?.status || "未检测"],
    ["输出目录", state.health?.storage?.writable, state.health?.storage?.writable ? "可写" : "未知"],
  ];
  connectionStatus.innerHTML = items.map(([name, ok, status]) => `
    <div class="status-item"><strong>${name}</strong><span class="badge ${ok ? "success" : "waiting"}">${escapeHtml(status)}</span></div>
  `).join("");
  topStatus.innerHTML = items.slice(0, 5).map(([name, ok, status]) => `
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
    ["ChatGPT Planner", state.checks.chatgpt?.status || "Mock/CDP Adapter"],
    ["Template Manager", "PPT/Word/材料上传"],
    ["Remote Access Auth", "本机模式默认开启，远程需 token"],
  ];
  toolRegistry.innerHTML = rows.map(([name, status]) => `<div class="registry-item"><strong>${name}</strong><span>${escapeHtml(status)}</span></div>`).join("");
}

function ensureAuditPanel() {
  if (phase2Audit) return;
  const filesCard = document.querySelector(".files-card");
  if (!filesCard) return;
  const section = document.createElement("section");
  section.className = "card status-card audit-card";
  section.innerHTML = `
    <h2>资料审计 / 人工核查</h2>
    <div id="phase2-audit" class="phase2-audit"></div>
  `;
  filesCard.insertAdjacentElement("afterend", section);
  phase2Audit = section.querySelector("#phase2-audit");
}

function renderPhase2AuditUnavailable(message, warnings = []) {
  ensureAuditPanel();
  if (!phase2Audit) return;
  const warningList = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
  phase2Audit.innerHTML = `
    <p class="audit-disclaimer">注意：以下审计信息用于辅助人工核查，不代表事实核验结论。请以原始来源和人工判断为准。</p>
    <p class="audit-empty">${escapeHtml(message || "审计信息暂不可用。")}</p>
    ${renderAuditWarnings(warningList)}
  `;
}

function renderPhase2Audit(data) {
  ensureAuditPanel();
  if (!phase2Audit) return;
  const warnings = Array.isArray(data?.warnings) ? data.warnings.filter(Boolean) : [];
  if (!data || !data.available) {
    renderPhase2AuditUnavailable("审计信息暂不可用。", warnings);
    return;
  }
  const metrics = [
    ["fallback_used", formatAuditBoolean(data.fallback_used)],
    ["source_count", data.source_count ?? 0],
    ["real_url_count", data.real_url_count ?? 0],
    ["manual_review_count", data.manual_review_count ?? 0],
  ];
  phase2Audit.innerHTML = `
    <p class="audit-disclaimer">注意：以下审计信息用于辅助人工核查，不代表事实核验结论。请以原始来源和人工判断为准。</p>
    <div class="audit-metrics">
      ${metrics.map(([label, value]) => `
        <div class="audit-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
      `).join("")}
    </div>
    <section class="audit-section">
      <h3>source_quality_summary</h3>
      ${renderAuditKeyValues(data.source_quality_summary, "暂无来源质量摘要")}
    </section>
    <section class="audit-section">
      <h3>audit_summary</h3>
      ${renderAuditKeyValues(data.audit_summary, "暂无审计摘要")}
    </section>
    <section class="audit-section">
      <h3>source_review_summary</h3>
      ${renderAuditKeyValues(data.review_summary, "暂无人工复核状态")}
    </section>
    <section class="audit-section">
      <h3>coverage</h3>
      ${renderCoverage(data.coverage)}
    </section>
    <section class="audit-section">
      <h3>manual_review_checklist</h3>
      ${renderAuditList(data.manual_review_checklist, "暂无人工核查清单")}
    </section>
    <section class="audit-section">
      <h3>候选来源人工核查</h3>
      ${renderAuditSources(data.sources)}
    </section>
    ${renderAuditWarnings(warnings)}
  `;
  bindAuditReviewControls();
}

function renderAuditKeyValues(value, emptyText) {
  const object = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const entries = Object.entries(object).filter(([, item]) => item !== undefined && item !== null && item !== "");
  if (!entries.length) return `<p class="audit-empty">${escapeHtml(emptyText)}</p>`;
  return `
    <dl class="audit-kv">
      ${entries.map(([key, item]) => `
        <div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatAuditValue(item))}</dd></div>
      `).join("")}
    </dl>
  `;
}

function renderCoverage(value) {
  const items = Array.isArray(value) ? value : [];
  if (!items.length) return `<p class="audit-empty">暂无覆盖摘要</p>`;
  return `
    <ul class="audit-list">
      ${items.map((item) => {
        if (!item || typeof item !== "object") return `<li>${escapeHtml(item)}</li>`;
        const queryId = item.query_id || item.id || "unknown";
        const sourceCount = item.candidate_source_count ?? item.source_count ?? 0;
        const found = item.has_candidate_sources ? "有候选来源" : "未找到候选来源";
        const failed = item.failed ? "；存在失败或需复查" : "";
        return `<li><strong>${escapeHtml(queryId)}</strong>：${escapeHtml(found)}；source_count=${escapeHtml(sourceCount)}${escapeHtml(failed)}</li>`;
      }).join("")}
    </ul>
  `;
}

function renderAuditList(value, emptyText) {
  const items = Array.isArray(value) ? value.filter(Boolean) : [];
  if (!items.length) return `<p class="audit-empty">${escapeHtml(emptyText)}</p>`;
  return `<ul class="audit-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderAuditSources(value) {
  const sources = Array.isArray(value) ? value : [];
  if (!sources.length) return `<p class="audit-empty">暂无候选来源</p>`;
  return `
    <div class="audit-source-list">
      ${sources.map((source) => renderAuditSource(source)).join("")}
    </div>
  `;
}

function renderAuditSource(source) {
  const item = source && typeof source === "object" ? source : {};
  const flags = Array.isArray(item.audit_flags) ? item.audit_flags.filter(Boolean) : [];
  const url = safeExternalUrl(item.url || item.normalized_url);
  const title = item.title || item.normalized_url || item.url || "(missing title)";
  const sourceKey = String(item.source_key || "");
  const reviewStatus = normalizeReviewStatus(item.review_status);
  const reviewNote = item.review_note || "";
  const reviewMeta = item.reviewed_at
    ? `reviewed_at=${item.reviewed_at} / reviewer=${item.reviewer || "local-user"}`
    : "尚未保存人工复核";
  const statusOptions = REVIEW_STATUS_OPTIONS.map((status) => `
    <option value="${escapeHtml(status)}" ${status === reviewStatus ? "selected" : ""}>${escapeHtml(REVIEW_STATUS_LABELS[status])}</option>
  `).join("");
  const flagHtml = flags.length
    ? flags.map((flag) => `<span>${escapeHtml(flag)}</span>`).join("")
    : `<span class="audit-flag-muted">无明显审计标记</span>`;
  return `
    <article class="audit-source ${item.needs_manual_review ? "needs-review" : ""}">
      <div class="audit-source-head">
        <strong>${escapeHtml(item.source_id || "source")}</strong>
        <span class="badge ${item.needs_manual_review ? "needs_review" : "success"}">needs_manual_review=${item.needs_manual_review ? "true" : "false"}</span>
      </div>
      ${url
        ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(title)}</a>`
        : `<span class="audit-source-title">${escapeHtml(title)}</span>`}
      <span class="audit-domain">${escapeHtml(item.domain || item.normalized_url || item.url || "unknown domain")}</span>
      <div class="audit-flags">${flagHtml}</div>
      <div class="audit-review" data-source-key="${escapeHtml(sourceKey)}">
        <div class="audit-review-status-line">
          <span>当前复核状态</span>
          <span class="badge review-${escapeHtml(reviewStatus)}">${escapeHtml(REVIEW_STATUS_LABELS[reviewStatus])}</span>
        </div>
        <div class="audit-review-row">
          <label>
            <span>复核状态</span>
            <select class="audit-review-status" data-source-key="${escapeHtml(sourceKey)}">${statusOptions}</select>
          </label>
          <button type="button" class="audit-review-save secondary" data-source-key="${escapeHtml(sourceKey)}">保存</button>
        </div>
        <label class="audit-review-note-field">
          <span>备注</span>
          <textarea class="audit-review-note" data-source-key="${escapeHtml(sourceKey)}" rows="2" maxlength="1000">${escapeHtml(reviewNote)}</textarea>
        </label>
        <span class="audit-review-meta">${escapeHtml(reviewMeta)}</span>
      </div>
    </article>
  `;
}

function bindAuditReviewControls() {
  if (!phase2Audit) return;
  phase2Audit.querySelectorAll(".audit-review-save").forEach((button) => {
    button.addEventListener("click", () => saveAuditSourceReview(button.dataset.sourceKey || "", button));
  });
}

async function saveAuditSourceReview(sourceKey, button) {
  if (!state.taskId) return showToast("尚未创建任务。");
  const panel = button.closest(".audit-review");
  if (!panel || !sourceKey) return showToast("来源复核状态缺少 source_key。");
  const reviewStatus = normalizeReviewStatus(panel.querySelector(".audit-review-status")?.value);
  const reviewNote = panel.querySelector(".audit-review-note")?.value || "";
  button.disabled = true;
  try {
    const result = await api(`/api/tasks/${state.taskId}/phase2/source-review`, {
      method: "POST",
      body: JSON.stringify({
        items: [
          {
            source_key: sourceKey,
            review_status: reviewStatus,
            review_note: reviewNote,
          },
        ],
      }),
    });
    logSystem("来源复核状态已保存", result);
    showToast("来源复核状态已保存。");
    await loadPhase2Audit();
  } catch (error) {
    logSystem("来源复核状态保存失败", { error: error.message });
    showToast(`来源复核保存失败：${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function normalizeReviewStatus(value) {
  return REVIEW_STATUS_LABELS[value] ? value : "unreviewed";
}

function renderAuditWarnings(warnings) {
  if (!warnings.length) return "";
  return `<div class="audit-warning">${warnings.map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>`;
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

function getRememberedCurrentTaskId() {
  try {
    return String(localStorage.getItem(CURRENT_TASK_KEY) || "").trim();
  } catch (error) {
    logSystem("Current task id read failed", { error: error.message });
    return "";
  }
}

function rememberCurrentTask(taskId) {
  if (!taskId) return;
  try {
    localStorage.setItem(CURRENT_TASK_KEY, taskId);
  } catch (error) {
    logSystem("Current task id save failed", { error: error.message });
  }
}

function forgetCurrentTask() {
  try {
    localStorage.removeItem(CURRENT_TASK_KEY);
  } catch (error) {
    logSystem("Current task id clear failed", { error: error.message });
  }
}

function rememberTask(record) {
  const summary = taskSummaryFromRecord(record);
  const existing = readStoredRecentTasks();
  const next = [
    summary,
    ...existing.filter((item) => item.task_id !== record.task_id),
  ].slice(0, 5);
  localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  state.taskHistory = mergeTaskSummaries([summary, ...state.taskHistory]);
  renderRecentTasks();
}

function renderRecentTasks() {
  const tasks = mergeTaskSummaries([...state.taskHistory, ...readStoredRecentTasks()]).slice(0, 10);
  if (!tasks.length) {
    recentTasks.textContent = "暂无最近任务";
    return;
  }
  recentTasks.innerHTML = tasks.map((task) => `
    <button type="button" class="recent-item ${task.task_id === state.taskId ? "active" : ""}" data-task-id="${escapeHtml(task.task_id)}">
      <strong>${escapeHtml(task.title || task.task_id)}</strong>
      <span>${escapeHtml(task.status || "unknown")} · ${escapeHtml(task.short_task_id || String(task.task_id || "").slice(0, 8))} · ${escapeHtml(formatTaskTime(task))}</span>
      <span>${escapeHtml(formatPhase2Flag(task))}</span>
    </button>
  `).join("");
  recentTasks.querySelectorAll(".recent-item").forEach((button) => {
    button.addEventListener("click", () => openHistoryTask(button.dataset.taskId || ""));
  });
}

function readStoredRecentTasks() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return normalizeTaskSummaries(raw ? JSON.parse(raw) : []);
  } catch (error) {
    logSystem("本地最近任务读取失败", { error: error.message });
    return [];
  }
}

function normalizeTaskSummaries(tasks) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter((task) => task && typeof task === "object" && task.task_id)
    .map((task) => ({
      task_id: String(task.task_id),
      short_task_id: String(task.short_task_id || task.task_id).slice(0, 8),
      title: String(task.title || task.request?.title || task.task_id),
      task_type: String(task.task_type || task.request?.task_type || ""),
      status: String(task.status || "unknown"),
      created_at: String(task.created_at || ""),
      updated_at: String(task.updated_at || task.created_at || ""),
      phase2_artifact_count: Number(task.phase2_artifact_count || 0),
      has_phase2_artifacts: Boolean(task.has_phase2_artifacts || Number(task.phase2_artifact_count || 0) > 0),
    }));
}

function mergeTaskSummaries(tasks) {
  const byId = new Map();
  normalizeTaskSummaries(tasks).forEach((task) => {
    if (!byId.has(task.task_id)) byId.set(task.task_id, task);
  });
  return [...byId.values()].sort((a, b) => (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at));
}

function taskSummaryFromRecord(record) {
  const phase2Files = Array.isArray(record.phase2_files) ? record.phase2_files : [];
  const phase2Count = phase2Files.filter((file) => file?.is_phase2_artifact).length;
  return {
    task_id: record.task_id,
    short_task_id: String(record.task_id || "").slice(0, 8),
    title: record.request?.title || record.task_id,
    task_type: record.request?.task_type || "",
    status: record.status || "unknown",
    created_at: record.created_at || "",
    updated_at: record.updated_at || record.created_at || "",
    phase2_artifact_count: phase2Count,
    has_phase2_artifacts: phase2Count > 0,
  };
}

function formatTaskTime(task) {
  return task.updated_at || task.created_at || "no time";
}

function formatPhase2Flag(task) {
  const count = Number(task.phase2_artifact_count || 0);
  return count > 0 ? `Phase 2 files: ${count}` : "Phase 2 files: none";
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

function isRunningStatus(status) {
  return status === "running";
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

function formatAuditBoolean(value) {
  if (value === null || value === undefined) return "未知";
  return value ? "true / 是" : "false / 否";
}

function formatAuditValue(value) {
  if (typeof value === "boolean") return formatAuditBoolean(value);
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return value.every((item) => typeof item !== "object") ? value.join(", ") : JSON.stringify(value);
  }
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

function safeExternalUrl(value) {
  const text = String(value || "").trim();
  return /^https?:\/\//i.test(text) ? text : "";
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
