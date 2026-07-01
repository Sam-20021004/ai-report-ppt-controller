const form = document.querySelector("#generator-form");
const steps = [...document.querySelectorAll(".step")];
const tabs = [...document.querySelectorAll(".tab")];
const panels = [...document.querySelectorAll(".tab-panel")];
const workflowStatus = document.querySelector("#workflow-status");
const downloadLink = document.querySelector("#download-link");
const confidenceBadge = document.querySelector("#confidence-badge");
const summaryList = document.querySelector("#summary-list");
const outlineList = document.querySelector("#outline-list");
const sourceList = document.querySelector("#source-list");
const slideCountLabel = document.querySelector("#slide-count-label");
const sourceCountLabel = document.querySelector("#source-count-label");
const toast = document.querySelector("#toast");
const actionButton = document.querySelector(".generate-action");
const searchButton = document.querySelector("#search-button");
const agentButton = document.querySelector("#agent-button");
const healthButton = document.querySelector("#health-button");
const installButton = document.querySelector("#install-button");
const uploadButton = document.querySelector("#upload-button");
const agentLog = document.querySelector("#agent-log code");
const agentStatus = document.querySelector("#agent-status");
const pptLog = document.querySelector("#ppt-log code");
const chromeLog = document.querySelector("#chrome-log code");
const pptMeta = document.querySelector("#ppt-meta");
const pptxReady = document.querySelector("#pptx-ready");
const searchProvider = document.querySelector("#search-provider");
const toolRegistry = document.querySelector("#tool-registry");

const stageLabels = ["正在检索公开来源", "正在整理分析", "正在生成大纲", "正在导出 PPTX"];
let latestResearch = null;

tabs.forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = getPayload();
  beginRun("生成PPT任务已启动");

  try {
    setStage(0);
    activateTab("workflow");
    const stageTimer = startStageTimer();
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    clearInterval(stageTimer);

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || data.error || "生成失败");
    }

    setStage(3);
    renderResult(data);
    activateTab("ppt");
    showToast("PPTX 已生成，可以下载。");
  } catch (error) {
    setStage(-1);
    writeAgentLog(`任务失败：${error.message || "未知错误"}`);
    writePptLog("导出失败，请检查后端日志或密钥配置。");
    showToast(error.message || "生成失败，请检查设置。");
  } finally {
    actionButton.disabled = false;
    actionButton.textContent = "生成PPT + Loop QA";
  }
});

searchButton.addEventListener("click", async () => {
  const payload = getPayload();
  searchButton.disabled = true;
  searchButton.textContent = "检索中";
  setStage(0);
  activateTab("search");

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const research = await response.json();
    if (!response.ok) {
      throw new Error(research.detail || research.error || "检索失败");
    }
    latestResearch = research;
    renderResearch(research);
    writeAgentLog(formatJson({
      action: "HTTP检索完成",
      topic: payload.topic,
      sourceCount: research.results.length,
      provider: research.usedProvider,
      findings: research.analysis.findings
    }));
    showToast("检索完成。");
  } catch (error) {
    showToast(error.message || "检索失败。");
    writeAgentLog(`检索失败：${error.message || "未知错误"}`);
  } finally {
    searchButton.disabled = false;
    searchButton.textContent = "HTTP 检索";
  }
});

agentButton.addEventListener("click", () => {
  activateTab("agent");
  agentStatus.textContent = "ready";
  const payload = getPayload();
  writeAgentLog(formatJson({
    agent: payload.agent,
    task: payload.topic,
    boundary: payload.searchBoundary,
    structure: payload.structure,
    latestResearch: latestResearch ? {
      sourceCount: latestResearch.results.length,
      confidence: latestResearch.analysis.confidence,
      findings: latestResearch.analysis.findings
    } : "尚未执行HTTP检索",
    nextStep: "点击“生成PPT + Loop QA”会生成大纲、写入PPTX并输出下载链接。"
  }));
  showToast("Agent任务上下文已准备。");
});

healthButton.addEventListener("click", checkHealth);

installButton.addEventListener("click", () => {
  activateTab("tools");
  showToast("本地后端、PPTX生成器和浏览器工作台已注册在页面中。");
  renderTools({
    ok: true,
    pptxReady: true,
    searchLabel: "按环境变量自动选择",
    upload: "本地后端"
  });
});

uploadButton.addEventListener("click", async () => {
  const input = document.querySelector("#materials");
  if (!input.files.length) {
    showToast("请选择要上传的材料。");
    return;
  }

  const formData = new FormData();
  [...input.files].forEach((file) => formData.append("materials", file));
  uploadButton.disabled = true;
  uploadButton.textContent = "上传中";

  try {
    const response = await fetch("/api/upload", {
      method: "POST",
      body: formData
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || data.error || "上传失败");
    }
    writeAgentLog(formatJson({
      action: "材料上传完成",
      files: data.files
    }));
    showToast(`已上传 ${data.files.length} 个文件。`);
  } catch (error) {
    showToast(error.message || "上传失败。");
  } finally {
    uploadButton.disabled = false;
    uploadButton.textContent = "上传到后端";
  }
});

checkHealth();

function getPayload() {
  const formData = new FormData(form);
  const boundary = String(formData.get("searchBoundary") || "").trim();
  const structure = String(formData.get("structure") || "").trim();
  const topic = String(formData.get("topic") || "").trim();

  return {
    topic,
    rawTopic: topic,
    searchBoundary: boundary,
    structure,
    audience: "业务决策者",
    tone: "专业、清晰、可执行",
    slideCount: Number(formData.get("slideCount")),
    searchDepth: Number(formData.get("searchDepth")),
    language: formData.get("language"),
    agent: formData.get("agent"),
    enableWeb: document.querySelector("#enableWeb").checked,
    includeNotes: document.querySelector("#includeNotes").checked
  };
}

function beginRun(message) {
  workflowStatus.textContent = message;
  downloadLink.classList.add("is-disabled");
  confidenceBadge.textContent = "生成中";
  summaryList.innerHTML = '<p class="empty-state">正在生成，请稍候。</p>';
  outlineList.innerHTML = "";
  slideCountLabel.textContent = "0 页";
  actionButton.disabled = true;
  actionButton.textContent = "生成中";
  writeAgentLog("任务已提交，等待后端检索与分析。");
  writePptLog("准备导出 PPTX。");
}

function startStageTimer() {
  let stage = 0;
  return setInterval(() => {
    stage = Math.min(stage + 1, 2);
    setStage(stage);
    workflowStatus.textContent = stageLabels[stage];
  }, 1600);
}

function setStage(activeIndex) {
  steps.forEach((step, index) => {
    step.classList.toggle("is-active", index === activeIndex);
    step.classList.toggle("is-done", activeIndex >= 0 && index < activeIndex);
  });
}

function renderResult(data) {
  const { deck, research, outline } = data;
  latestResearch = research;
  workflowStatus.textContent = "已完成";
  confidenceBadge.textContent = confidenceText(research.analysis.confidence);
  slideCountLabel.textContent = `${deck.slideCount} 页`;
  downloadLink.href = deck.downloadUrl;
  downloadLink.classList.remove("is-disabled");
  pptMeta.textContent = `${deck.fileName} | ${deck.slideCount} 页 | ${new Date(deck.generatedAt).toLocaleString()}`;
  writePptLog(formatJson({
    status: "exported",
    fileName: deck.fileName,
    downloadUrl: deck.downloadUrl,
    slideCount: deck.slideCount,
    path: deck.path
  }));

  renderTakeaways(outline.takeaways && outline.takeaways.length ? outline.takeaways : research.analysis.findings);
  renderOutline(outline.slides);
  renderResearch(research);
  writeAgentLog(formatJson({
    status: "completed",
    title: outline.title,
    sourceCount: research.results.length,
    confidence: research.analysis.confidence,
    takeaways: outline.takeaways
  }));
}

function renderResearch(research) {
  sourceCountLabel.textContent = `${research.results.length} 个来源`;
  sourceProviderStatus(research.usedProvider);
  renderTakeaways(research.analysis.findings);

  sourceList.innerHTML = "";
  if (!research.results.length) {
    sourceList.innerHTML = '<p class="empty-state">没有可展示的在线来源。</p>';
    return;
  }

  research.results.forEach((source) => {
    const card = document.createElement("article");
    card.className = "source-card";
    card.innerHTML = `
      <a href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer">[${source.id}] ${escapeHtml(source.title)}</a>
      <p>${escapeHtml(source.snippet || "无摘要")}</p>
      <span>${escapeHtml(source.domain || source.provider || "")}</span>
    `;
    sourceList.appendChild(card);
  });
}

function renderTakeaways(takeaways) {
  summaryList.innerHTML = "";
  const list = takeaways && takeaways.length ? takeaways : ["暂无分析结论。"];
  list.forEach((item) => {
    const row = document.createElement("div");
    row.className = "summary-item";
    row.innerHTML = `<p>${escapeHtml(item)}</p>`;
    summaryList.appendChild(row);
  });
}

function renderOutline(slides) {
  outlineList.innerHTML = "";
  (slides || []).forEach((slide, index) => {
    const row = document.createElement("article");
    row.className = "slide-row";
    const bullets = (slide.bullets || []).slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    row.innerHTML = `
      <div class="slide-num">${index + 1}</div>
      <div>
        <h3>${escapeHtml(slide.title)}</h3>
        <p>${escapeHtml(slide.insight || "")}</p>
        <ul>${bullets}</ul>
      </div>
    `;
    outlineList.appendChild(row);
  });
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    pptxReady.textContent = data.pptxReady ? "PPTX：可用" : "PPTX：不可用";
    searchProvider.textContent = "搜索：自动选择";
    renderTools({
      ok: data.ok,
      pptxReady: data.pptxReady,
      searchLabel: "Brave/Bing/Tavily/SerpAPI/DuckDuckGo",
      upload: "本地后端"
    });
    chromeLog.textContent = formatJson({
      status: "connected",
      app: "Research PPT Generator",
      endpoint: "http://localhost:5176",
      cdpDefault: "127.0.0.1:9222"
    });
    showToast(data.pptxReady ? "后端连接正常。" : "后端在线，但PPTX依赖不可用。");
  } catch (error) {
    pptxReady.textContent = "PPTX：未知";
    searchProvider.textContent = "搜索：未知";
    chromeLog.textContent = formatJson({ status: "offline", error: error.message });
    showToast("无法连接后端服务。");
  }
}

function renderTools(status) {
  toolRegistry.innerHTML = `
    <div><strong>HTTP检索</strong><span>${escapeHtml(status.searchLabel || "自动选择")}</span></div>
    <div><strong>PPTX生成</strong><span>${status.pptxReady ? "可用" : "不可用"}</span></div>
    <div><strong>模型增强</strong><span>可选 OPENAI_API_KEY</span></div>
    <div><strong>材料上传</strong><span>${escapeHtml(status.upload || "本地后端")}</span></div>
  `;
}

function activateTab(name) {
  tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name));
  panels.forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
}

function sourceProviderStatus(provider) {
  searchProvider.textContent = `搜索：${provider || "自动选择"}`;
}

function writeAgentLog(message) {
  agentLog.textContent = message;
}

function writePptLog(message) {
  pptLog.textContent = message;
}

function confidenceText(value) {
  if (value === "high") return "高置信度";
  if (value === "medium") return "中置信度";
  return "低置信度";
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("is-hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.classList.add("is-hidden");
  }, 3600);
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}
