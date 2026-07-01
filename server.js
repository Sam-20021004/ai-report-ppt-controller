const http = require("http");
const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

const ROOT = __dirname;
const PUBLIC_DIR = path.join(ROOT, "public");
const OUTPUT_DIR = path.join(ROOT, "outputs");
const UPLOAD_DIR = path.join(ROOT, "uploads");
const PORT = Number(process.env.PORT || 5176);
const CURRENT_YEAR = new Date().getFullYear();

fs.mkdirSync(OUTPUT_DIR, { recursive: true });
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
};

function loadModule(name) {
  try {
    return require(name);
  } catch (error) {
    const candidates = [
      process.env.NODE_PATH,
      path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules")
    ].filter(Boolean);

    for (const base of candidates) {
      const pnpmModule = resolvePnpmModule(base, name);
      if (pnpmModule) {
        try {
          return require(pnpmModule);
        } catch (_) {
          // Fall back to the package path below.
        }
      }

      try {
        return require(path.join(base, name));
      } catch (_) {
        // Try the next known dependency location.
      }
    }

    throw error;
  }
}

function resolvePnpmModule(base, name) {
  const store = path.join(base, ".pnpm");
  if (!fs.existsSync(store)) return null;

  const prefix = name.startsWith("@")
    ? `${name.replace("/", "+")}@`
    : `${name}@`;

  const entry = fs.readdirSync(store).find((item) => item.startsWith(prefix));
  if (!entry) return null;
  return path.join(store, entry, "node_modules", name);
}

let PptxGenJS = null;
let pptxLoadError = null;
try {
  PptxGenJS = loadModule("pptxgenjs");
} catch (error) {
  pptxLoadError = error;
}

const server = http.createServer(async (req, res) => {
  try {
    const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);

    if (req.method === "GET" && requestUrl.pathname === "/api/health") {
      return sendJson(res, 200, {
        ok: true,
        pptxReady: Boolean(PptxGenJS),
        pptxError: pptxLoadError ? pptxLoadError.message : null
      });
    }

    if (req.method === "POST" && requestUrl.pathname === "/api/search") {
      const input = await readJson(req);
      const normalized = normalizeInput(input);
      const research = await runResearch(normalized);
      return sendJson(res, 200, research);
    }

    if (req.method === "POST" && requestUrl.pathname === "/api/generate") {
      if (!PptxGenJS) {
        return sendJson(res, 500, {
          error: "PPTX generation library is not available.",
          detail: pptxLoadError ? pptxLoadError.message : "Unknown module load error"
        });
      }

      const input = normalizeInput(await readJson(req));
      const research = input.enableWeb ? await runResearch(input) : createEmptyResearch(input);
      const outline = await buildOutline(input, research);
      const deck = await createDeck(input, research, outline);

      return sendJson(res, 200, {
        ok: true,
        deck,
        research,
        outline
      });
    }

    if (req.method === "POST" && requestUrl.pathname === "/api/upload") {
      const files = await receiveUpload(req);
      return sendJson(res, 200, {
        ok: true,
        files
      });
    }

    if (req.method === "GET" && requestUrl.pathname.startsWith("/download/")) {
      return serveDownload(req, res, decodeURIComponent(requestUrl.pathname.replace("/download/", "")));
    }

    if (req.method === "GET") {
      return serveStatic(req, res, requestUrl.pathname);
    }

    return sendJson(res, 405, { error: "Method not allowed" });
  } catch (error) {
    return sendJson(res, 500, {
      error: "Request failed",
      detail: error.message
    });
  }
});

server.listen(PORT, () => {
  console.log(`Research PPT Generator running at http://localhost:${PORT}`);
});

function normalizeInput(input) {
  const value = input || {};
  const topic = String(value.rawTopic || value.topic || "").trim();
  if (!topic) {
    throw new Error("Topic is required.");
  }

  const language = value.language === "en" ? "en" : "zh";
  return {
    topic,
    searchBoundary: clip(String(value.searchBoundary || "").trim(), 600),
    structure: clip(String(value.structure || "").trim(), 1200),
    audience: clip(String(value.audience || (language === "zh" ? "业务决策者" : "business decision makers")).trim(), 80),
    tone: clip(String(value.tone || (language === "zh" ? "专业、清晰、可执行" : "professional, clear, actionable")).trim(), 80),
    slideCount: clamp(Number(value.slideCount || 8), 5, 12),
    searchDepth: clamp(Number(value.searchDepth || 2), 1, 4),
    language,
    includeNotes: value.includeNotes !== false,
    enableWeb: value.enableWeb !== false
  };
}

function createEmptyResearch(input) {
  const analysis = analyzeSources([], input);
  return {
    topic: input.topic,
    queries: [],
    results: [],
    analysis,
    providerErrors: [],
    usedProvider: "none"
  };
}

async function runResearch(input) {
  const queries = buildSearchQueries(input);
  const providerErrors = [];
  const buckets = [];

  for (const query of queries) {
    try {
      const results = await searchWeb(query, 5 + input.searchDepth, input.language);
      buckets.push(...results.map((result) => ({ ...result, query })));
    } catch (error) {
      providerErrors.push(`${query}: ${error.message}`);
    }
  }

  const results = dedupeResults(buckets)
    .slice(0, 14)
    .map((result, index) => ({
      ...result,
      id: index + 1,
      domain: getDomain(result.url)
    }));

  return {
    topic: input.topic,
    queries,
    results,
    analysis: analyzeSources(results, input),
    providerErrors,
    usedProvider: detectSearchProvider()
  };
}

function buildSearchQueries(input) {
  const topic = clip([input.topic, input.searchBoundary].filter(Boolean).join(" "), 140);
  const zh = input.language === "zh";
  const depthQueries = zh
    ? [
        `${topic} 最新趋势 ${CURRENT_YEAR}`,
        `${topic} 市场规模 数据 报告`,
        `${topic} 主要挑战 风险`,
        `${topic} 案例 解决方案`,
        `${topic} 未来发展 机会`
      ]
    : [
        `${topic} latest trends ${CURRENT_YEAR}`,
        `${topic} market size data report`,
        `${topic} key challenges risks`,
        `${topic} case studies solutions`,
        `${topic} future outlook opportunities`
      ];

  return depthQueries.slice(0, input.searchDepth + 1);
}

function detectSearchProvider() {
  if (process.env.BRAVE_SEARCH_API_KEY) return "Brave Search API";
  if (process.env.BING_SEARCH_API_KEY) return "Bing Web Search API";
  if (process.env.TAVILY_API_KEY) return "Tavily Search API";
  if (process.env.SERPAPI_KEY || process.env.SERPAPI_API_KEY) return "SerpAPI";
  return "DuckDuckGo public search";
}

async function searchWeb(query, count, language) {
  if (process.env.BRAVE_SEARCH_API_KEY) return searchBrave(query, count);
  if (process.env.BING_SEARCH_API_KEY) return searchBing(query, count);
  if (process.env.TAVILY_API_KEY) return searchTavily(query, count);
  if (process.env.SERPAPI_KEY || process.env.SERPAPI_API_KEY) return searchSerpApi(query, count);

  const duckResults = await searchDuckDuckGoHtml(query, count);
  if (duckResults.length) return duckResults;
  return searchDuckDuckGoInstant(query, count, language);
}

async function searchBrave(query, count) {
  const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=${count}`;
  const response = await fetchWithTimeout(url, {
    headers: {
      "Accept": "application/json",
      "X-Subscription-Token": process.env.BRAVE_SEARCH_API_KEY
    }
  });
  if (!response.ok) throw new Error(`Brave Search returned ${response.status}`);
  const data = await response.json();
  return (data.web && data.web.results ? data.web.results : []).map((item) => ({
    title: item.title,
    url: item.url,
    snippet: item.description || "",
    provider: "Brave Search API"
  }));
}

async function searchBing(query, count) {
  const url = `https://api.bing.microsoft.com/v7.0/search?q=${encodeURIComponent(query)}&count=${count}`;
  const response = await fetchWithTimeout(url, {
    headers: {
      "Ocp-Apim-Subscription-Key": process.env.BING_SEARCH_API_KEY
    }
  });
  if (!response.ok) throw new Error(`Bing Search returned ${response.status}`);
  const data = await response.json();
  return ((data.webPages && data.webPages.value) || []).map((item) => ({
    title: item.name,
    url: item.url,
    snippet: item.snippet || "",
    provider: "Bing Web Search API"
  }));
}

async function searchTavily(query, count) {
  const response = await fetchWithTimeout("https://api.tavily.com/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.TAVILY_API_KEY}`
    },
    body: JSON.stringify({
      query,
      max_results: count,
      search_depth: "advanced",
      include_answer: false
    })
  });
  if (!response.ok) throw new Error(`Tavily returned ${response.status}`);
  const data = await response.json();
  return (data.results || []).map((item) => ({
    title: item.title,
    url: item.url,
    snippet: item.content || "",
    provider: "Tavily Search API"
  }));
}

async function searchSerpApi(query, count) {
  const key = process.env.SERPAPI_KEY || process.env.SERPAPI_API_KEY;
  const url = `https://serpapi.com/search.json?engine=google&q=${encodeURIComponent(query)}&num=${count}&api_key=${encodeURIComponent(key)}`;
  const response = await fetchWithTimeout(url);
  if (!response.ok) throw new Error(`SerpAPI returned ${response.status}`);
  const data = await response.json();
  return (data.organic_results || []).map((item) => ({
    title: item.title,
    url: item.link,
    snippet: item.snippet || "",
    provider: "SerpAPI"
  }));
}

async function searchDuckDuckGoHtml(query, count) {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const response = await fetchWithTimeout(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 ResearchDeckStudio/1.0"
    }
  }, 12000);
  if (!response.ok) throw new Error(`DuckDuckGo returned ${response.status}`);

  const html = await response.text();
  const results = [];
  const linkRegex = /<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  let match;

  while ((match = linkRegex.exec(html)) && results.length < count) {
    const href = normalizeDuckDuckGoUrl(decodeHtml(match[1]));
    const title = cleanText(match[2]);
    const nearby = html.slice(linkRegex.lastIndex, linkRegex.lastIndex + 2500);
    const snippetMatch = nearby.match(/class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/(?:a|div)>/i);
    const snippet = snippetMatch ? cleanText(snippetMatch[1]) : "";
    if (title && href) {
      results.push({
        title,
        url: href,
        snippet,
        provider: "DuckDuckGo public search"
      });
    }
  }

  return results;
}

async function searchDuckDuckGoInstant(query, count) {
  const url = `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`;
  const response = await fetchWithTimeout(url, {}, 10000);
  if (!response.ok) throw new Error(`DuckDuckGo Instant Answer returned ${response.status}`);
  const data = await response.json();
  const results = [];

  if (data.AbstractText && data.AbstractURL) {
    results.push({
      title: data.Heading || query,
      url: data.AbstractURL,
      snippet: data.AbstractText,
      provider: "DuckDuckGo Instant Answer"
    });
  }

  for (const topic of flattenRelatedTopics(data.RelatedTopics || [])) {
    if (results.length >= count) break;
    if (topic.Text && topic.FirstURL) {
      results.push({
        title: topic.Text.split(" - ")[0] || query,
        url: topic.FirstURL,
        snippet: topic.Text,
        provider: "DuckDuckGo Instant Answer"
      });
    }
  }

  return results;
}

function flattenRelatedTopics(items) {
  const output = [];
  for (const item of items) {
    if (Array.isArray(item.Topics)) output.push(...flattenRelatedTopics(item.Topics));
    else output.push(item);
  }
  return output;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal
    });
  } finally {
    clearTimeout(timer);
  }
}

function analyzeSources(results, input) {
  const domains = countBy(results.map((result) => result.domain || getDomain(result.url)).filter(Boolean));
  const themeScores = extractThemes(results, input.language);
  const credible = results
    .filter((result) => /(\.gov|\.edu|who\.int|worldbank|oecd|imf|mckinsey|gartner|forrester|statista|pwc|deloitte|accenture)/i.test(result.domain || ""))
    .slice(0, 5);
  const findings = buildFindings(results, input, themeScores);

  return {
    sourceCount: results.length,
    topDomains: Object.entries(domains)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([domain, count]) => ({ domain, count })),
    themes: themeScores.slice(0, 8),
    credibleSources: credible.map((result) => result.id),
    findings,
    confidence: results.length >= 8 ? "high" : results.length >= 4 ? "medium" : "low"
  };
}

function extractThemes(results, language) {
  const stop = language === "zh"
    ? new Set(["以及", "一个", "相关", "最新", "市场", "报告", "数据", "趋势", "主要", "发展"])
    : new Set(["the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "into", "latest", "market", "report", "data", "about", "overview", "analysis"]);

  const text = results.map((result) => `${result.title || ""} ${result.snippet || ""}`).join(" ").toLowerCase();
  const words = text.match(language === "zh" ? /[\u4e00-\u9fa5]{2,6}/g : /[a-z][a-z0-9-]{3,}/g) || [];
  const counts = new Map();

  for (const word of words) {
    if (stop.has(word)) continue;
    counts.set(word, (counts.get(word) || 0) + 1);
  }

  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([term, count]) => ({ term, count }));
}

function buildFindings(results, input, themes) {
  const zh = input.language === "zh";
  const themeText = themes.slice(0, 4).map((theme) => theme.term).join(zh ? "、" : ", ");
  const hasSources = results.length > 0;

  if (!hasSources) {
    return zh
      ? [
          `围绕“${input.topic}”先建立问题框架，再补充可验证数据来源。`,
          "当前没有可用搜索结果，建议在使用时配置搜索 API 以增强证据质量。",
          "演示稿将以策略分析、风险识别和行动路线为主线。"
        ]
      : [
          `Start with a problem frame for "${input.topic}", then add verifiable source evidence.`,
          "No live search results were available; configure a search API for stronger evidence.",
          "The deck will center on strategic analysis, risk recognition, and an action path."
        ];
  }

  return zh
    ? [
        `搜索结果集中指向 ${themeText || input.topic} 等高频主题。`,
        `可引用来源数量为 ${results.length} 个，证据覆盖 ${new Set(results.map((item) => item.domain)).size} 个域名。`,
        `建议将论述聚焦在“现状判断、机会识别、风险控制、行动路线”四段。`
      ]
    : [
        `Search results cluster around ${themeText || input.topic}.`,
        `${results.length} citeable sources span ${new Set(results.map((item) => item.domain)).size} domains.`,
        "The strongest story arc is context, opportunities, risks, and action plan."
      ];
}

async function buildOutline(input, research) {
  const aiOutline = await buildOutlineWithOpenAI(input, research).catch(() => null);
  if (aiOutline && Array.isArray(aiOutline.slides) && aiOutline.slides.length >= 5) {
    return normalizeOutline(aiOutline, input, research);
  }
  return buildLocalOutline(input, research);
}

async function buildOutlineWithOpenAI(input, research) {
  if (!process.env.OPENAI_API_KEY) return null;

  const system = input.language === "zh"
    ? "你是资深策略顾问。请基于给定搜索结果，输出结构化 PPT 大纲 JSON。不要编造来源之外的具体数字。"
    : "You are a senior strategy consultant. Build a structured presentation outline JSON from the supplied search results. Do not invent specific numbers beyond the sources.";

  const prompt = {
    topic: input.topic,
    searchBoundary: input.searchBoundary,
    requiredStructure: input.structure,
    audience: input.audience,
    tone: input.tone,
    slideCount: input.slideCount,
    language: input.language,
    searchResults: research.results.map((result) => ({
      id: result.id,
      title: result.title,
      url: result.url,
      snippet: result.snippet
    })),
    requiredSchema: {
      title: "string",
      subtitle: "string",
      takeaways: ["string"],
      slides: [
        {
          title: "string",
          kicker: "string",
          insight: "string",
          bullets: ["string"],
          sourceIndexes: ["number"],
          visual: "string"
        }
      ]
    }
  };

  const response = await fetchWithTimeout("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${process.env.OPENAI_API_KEY}`
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || "gpt-4o-mini",
      temperature: 0.25,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: system },
        { role: "user", content: JSON.stringify(prompt) }
      ]
    })
  }, 30000);

  if (!response.ok) throw new Error(`OpenAI returned ${response.status}`);
  const data = await response.json();
  return JSON.parse(data.choices[0].message.content);
}

function buildLocalOutline(input, research) {
  const zh = input.language === "zh";
  const themes = research.analysis.themes.map((theme) => theme.term);
  const sources = research.results;
  const topSources = sources.slice(0, 6).map((source) => source.id);
  const title = zh ? `${input.topic}研究与行动建议` : `${input.topic}: Research and Action Plan`;
  const subtitle = zh
    ? `${input.audience} | ${input.tone}`
    : `${input.audience} | ${input.tone}`;

  const requestedSections = parseStructure(input.structure);
  const slidePool = [
    {
      role: "title",
      title,
      kicker: zh ? "研究型演示稿" : "Research deck",
      insight: zh ? "基于公开来源的快速研判。" : "A fast readout based on public sources.",
      bullets: research.analysis.findings.slice(0, 2),
      sourceIndexes: topSources.slice(0, 3),
      visual: "cover"
    },
    {
      title: zh ? "核心结论" : "Executive Summary",
      kicker: zh ? "判断" : "Readout",
      insight: zh ? "先给出可执行判断，再展开证据。" : "Lead with decisions, then unpack the evidence.",
      bullets: research.analysis.findings,
      sourceIndexes: topSources.slice(0, 4),
      visual: "summary"
    },
    ...requestedSections.map((section, index) => ({
      title: section,
      kicker: zh ? "结构输入" : "Requested section",
      insight: zh
        ? `围绕“${section}”组织证据、判断和行动含义。`
        : `Organize evidence, judgment, and action implications around "${section}".`,
      bullets: buildSectionBullets(section, input, research, index),
      sourceIndexes: topSources.slice(index % 3, index % 3 + 4),
      visual: visualForTitle(section)
    })),
    {
      title: zh ? "为什么现在值得关注" : "Why It Matters Now",
      kicker: zh ? "背景" : "Context",
      insight: zh ? "搜索证据显示，该主题正在被趋势、数据与案例共同推动。" : "The evidence points to momentum across trends, data, and cases.",
      bullets: [
        zh ? `高频主题：${themes.slice(0, 4).join("、") || input.topic}` : `High-frequency themes: ${themes.slice(0, 4).join(", ") || input.topic}`,
        zh ? `来源覆盖：${research.analysis.sourceCount} 个结果，${research.analysis.topDomains.length} 类主要域名。` : `Coverage: ${research.analysis.sourceCount} results across ${research.analysis.topDomains.length} leading domains.`,
        zh ? "适合从市场、用户、技术与组织能力四个维度拆解。" : "Frame the topic through market, user, technology, and capability lenses."
      ],
      sourceIndexes: topSources.slice(0, 4),
      visual: "trend"
    },
    {
      title: zh ? "证据地图" : "Evidence Map",
      kicker: zh ? "来源" : "Sources",
      insight: zh ? "优先使用可追溯来源，避免把单一观点当作结论。" : "Use traceable evidence and avoid over-weighting a single viewpoint.",
      bullets: buildEvidenceBullets(research, input),
      sourceIndexes: topSources,
      visual: "evidence"
    },
    {
      title: zh ? "主要机会" : "Primary Opportunities",
      kicker: zh ? "机会" : "Opportunities",
      insight: zh ? "机会通常来自需求变化、效率提升和差异化定位。" : "Opportunities usually emerge from demand shifts, efficiency gains, and differentiated positioning.",
      bullets: [
        zh ? "把高频主题转化为可验证的业务假设。" : "Turn high-frequency themes into testable business hypotheses.",
        zh ? "优先寻找可用数据、成熟案例和明确买方痛点。" : "Prioritize available data, mature cases, and clear buyer pain points.",
        zh ? "用小范围试点降低认知和执行不确定性。" : "Use focused pilots to reduce learning and execution uncertainty."
      ],
      sourceIndexes: topSources.slice(1, 5),
      visual: "opportunity"
    },
    {
      title: zh ? "关键风险与约束" : "Risks and Constraints",
      kicker: zh ? "风险" : "Risks",
      insight: zh ? "需要同时评估证据质量、落地复杂度和外部依赖。" : "Assess evidence quality, implementation complexity, and outside dependencies together.",
      bullets: [
        zh ? "搜索结果可能存在时效差异，应补充一手数据或权威报告。" : "Search results may vary in freshness; add first-party data or authoritative reports.",
        zh ? "策略落地会受到预算、流程、合规和人才能力约束。" : "Execution depends on budget, process, compliance, and talent constraints.",
        zh ? "对强结论保留置信度标记，避免过度承诺。" : "Mark confidence on strong claims to avoid over-commitment."
      ],
      sourceIndexes: topSources.slice(2, 6),
      visual: "risk"
    },
    {
      title: zh ? "建议路径" : "Recommended Path",
      kicker: zh ? "策略" : "Strategy",
      insight: zh ? "从明确目标、验证假设、形成机制三个阶段推进。" : "Move through goals, hypothesis testing, and operating rhythm.",
      bullets: [
        zh ? "第 1 阶段：明确业务问题、成功指标与决策边界。" : "Phase 1: define business problem, success metrics, and decision boundaries.",
        zh ? "第 2 阶段：围绕最高价值机会做 2-3 个验证动作。" : "Phase 2: run 2-3 validation moves around the highest-value opportunities.",
        zh ? "第 3 阶段：沉淀流程、数据看板和复盘机制。" : "Phase 3: institutionalize process, dashboards, and review cadence."
      ],
      sourceIndexes: topSources.slice(0, 5),
      visual: "roadmap"
    },
    {
      title: zh ? "下一步行动清单" : "Next Actions",
      kicker: zh ? "执行" : "Execution",
      insight: zh ? "把研究结论转成具体负责人、时间点和验收标准。" : "Translate research into owners, dates, and acceptance criteria.",
      bullets: [
        zh ? "补充 3-5 个权威来源，验证关键数字和行业口径。" : "Add 3-5 authoritative sources to validate key numbers and definitions.",
        zh ? "访谈内部/外部利益相关方，校准优先级。" : "Interview internal and external stakeholders to calibrate priorities.",
        zh ? "在两周内形成试点方案和风险清单。" : "Produce a pilot plan and risk register within two weeks."
      ],
      sourceIndexes: topSources.slice(0, 4),
      visual: "actions"
    },
    {
      title: zh ? "引用来源" : "Sources",
      kicker: zh ? "附录" : "Appendix",
      insight: zh ? "以下来源用于形成研究判断。" : "The following sources informed the research readout.",
      bullets: buildSourceBullets(research.results, input.language),
      sourceIndexes: topSources,
      visual: "sources"
    }
  ];

  const selected = selectSlides(slidePool, input.slideCount);
  return normalizeOutline({
    title,
    subtitle,
    takeaways: research.analysis.findings,
    slides: selected
  }, input, research);
}

function parseStructure(value) {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)、]|[A-Z]\d*[.)、]?)\s*/i, "").trim())
    .filter(Boolean)
    .slice(0, 8);
}

function buildSectionBullets(section, input, research, index) {
  const zh = input.language === "zh";
  const themes = research.analysis.themes.slice(index, index + 3).map((theme) => theme.term);
  const themeText = themes.length ? themes.join(zh ? "、" : ", ") : input.topic;
  return zh
    ? [
        `结合高频主题：${themeText}。`,
        "提炼该章节下的关键判断与证据缺口。",
        "输出可执行建议，并标记需要复核的数据。"
      ]
    : [
        `Connect this section to themes: ${themeText}.`,
        "Extract the main judgment and evidence gaps.",
        "Translate findings into actions and mark claims for validation."
      ];
}

function visualForTitle(title) {
  if (/风险|约束|risk|constraint/i.test(title)) return "risk";
  if (/行动|路线|建议|roadmap|action|next/i.test(title)) return "roadmap";
  if (/来源|证据|检索|source|evidence|research/i.test(title)) return "evidence";
  if (/机会|应用|场景|opportunity|use case|case/i.test(title)) return "opportunity";
  return "trend";
}

function normalizeOutline(outline, input, research) {
  const slides = (outline.slides || []).slice(0, input.slideCount).map((slide, index) => ({
    title: clip(String(slide.title || `Slide ${index + 1}`), 90),
    kicker: clip(String(slide.kicker || ""), 40),
    insight: clip(String(slide.insight || ""), 190),
    bullets: ensureArray(slide.bullets).slice(0, 5).map((text) => clip(String(text), 150)),
    sourceIndexes: ensureArray(slide.sourceIndexes)
      .map(Number)
      .filter((id) => research.results.some((result) => result.id === id))
      .slice(0, 6),
    visual: slide.visual || "content",
    role: slide.role || ""
  }));

  while (slides.length < input.slideCount) {
    slides.push({
      title: input.language === "zh" ? "补充观察" : "Additional Observation",
      kicker: input.language === "zh" ? "补充" : "Additional",
      insight: input.language === "zh" ? "该页用于承接进一步资料或内部数据。" : "This page can carry additional material or first-party data.",
      bullets: input.language === "zh" ? ["补充权威来源。", "校准关键假设。", "更新行动计划。"] : ["Add authoritative sources.", "Calibrate key assumptions.", "Update the action plan."],
      sourceIndexes: [],
      visual: "content"
    });
  }

  return {
    title: clip(String(outline.title || (input.language === "zh" ? `${input.topic}研究` : `${input.topic} Research`)), 100),
    subtitle: clip(String(outline.subtitle || input.audience), 140),
    takeaways: ensureArray(outline.takeaways).slice(0, 4).map((text) => clip(String(text), 160)),
    slides
  };
}

function selectSlides(slidePool, count) {
  if (count >= slidePool.length) return slidePool.slice(0, count);
  const title = slidePool[0];
  const summary = slidePool[1];
  const sources = slidePool[slidePool.length - 1];
  const middle = slidePool.slice(2, -1);
  return [title, summary, ...middle.slice(0, count - 3), sources];
}

function buildEvidenceBullets(research, input) {
  const zh = input.language === "zh";
  if (!research.results.length) {
    return zh
      ? ["暂无在线来源；建议配置搜索 API。", "先用内部数据补充行业背景。", "所有关键数字在发布前需要复核。"]
      : ["No online sources available; configure a search API.", "Add internal data for industry context.", "Verify all key figures before publishing."];
  }

  return research.analysis.topDomains.slice(0, 5).map((item) => (
    zh
      ? `${item.domain} 提供 ${item.count} 条相关线索。`
      : `${item.domain} contributes ${item.count} relevant lead${item.count > 1 ? "s" : ""}.`
  ));
}

function buildSourceBullets(results, language) {
  if (!results.length) return language === "zh" ? ["未检索到可引用来源。"] : ["No citeable sources found."];
  return results.slice(0, 8).map((result) => `[${result.id}] ${clip(result.title, 95)} (${result.domain})`);
}

async function createDeck(input, research, outline) {
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "Research PPT Generator";
  pptx.company = "Local app";
  pptx.subject = input.topic;
  pptx.title = outline.title;
  pptx.lang = input.language === "zh" ? "zh-CN" : "en-US";
  pptx.theme = {
    headFontFace: input.language === "zh" ? "Microsoft YaHei" : "Aptos Display",
    bodyFontFace: input.language === "zh" ? "Microsoft YaHei" : "Aptos",
    lang: input.language === "zh" ? "zh-CN" : "en-US"
  };
  pptx.defineLayout({ name: "APP_WIDE", width: 13.333, height: 7.5 });
  pptx.layout = "APP_WIDE";

  outline.slides.forEach((slideModel, index) => {
    if (index === 0 || slideModel.role === "title") {
      addTitleSlide(pptx, slideModel, outline, input, research);
    } else if (/sources|引用|source/i.test(slideModel.title + slideModel.visual)) {
      addSourcesSlide(pptx, slideModel, input, research, index + 1, outline.slides.length);
    } else {
      addContentSlide(pptx, slideModel, input, research, index + 1, outline.slides.length);
    }
  });

  const fileBase = `${slugify(input.topic)}-${Date.now().toString(36)}`;
  const fileName = `${fileBase}.pptx`;
  const absolutePath = path.join(OUTPUT_DIR, fileName);
  await pptx.writeFile({ fileName: absolutePath });

  return {
    fileName,
    path: absolutePath,
    downloadUrl: `/download/${encodeURIComponent(fileName)}`,
    slideCount: outline.slides.length,
    generatedAt: new Date().toISOString()
  };
}

function addTitleSlide(pptx, model, outline, input, research) {
  const slide = pptx.addSlide();
  const p = palette();
  slide.background = { color: p.paper };
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.333, h: 7.5, fill: { color: p.paper }, line: { color: p.paper } });
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.18, h: 7.5, fill: { color: p.coral }, line: { color: p.coral } });
  slide.addShape(pptx.ShapeType.rect, { x: 9.55, y: 0, w: 3.783, h: 7.5, fill: { color: p.charcoal }, line: { color: p.charcoal } });
  slide.addShape(pptx.ShapeType.rect, { x: 9.55, y: 4.7, w: 3.783, h: 2.8, fill: { color: p.teal }, line: { color: p.teal } });

  slide.addText(model.kicker || (input.language === "zh" ? "研究型演示稿" : "Research deck"), {
    x: 0.72, y: 0.7, w: 7.9, h: 0.35,
    fontFace: font(input), fontSize: 15, bold: true, color: p.teal,
    margin: 0
  });
  slide.addText(outline.title, {
    x: 0.72, y: 1.32, w: 8.25, h: 1.75,
    fontFace: font(input), fontSize: 50, bold: true, color: p.ink,
    margin: 0.02, breakLine: false, fit: "shrink"
  });
  slide.addText(outline.subtitle, {
    x: 0.76, y: 3.22, w: 7.45, h: 0.52,
    fontFace: font(input), fontSize: 20, color: p.muted,
    margin: 0
  });
  slide.addText(model.insight || "", {
    x: 0.76, y: 4.02, w: 7.4, h: 0.75,
    fontFace: font(input), fontSize: 22, bold: true, color: p.ink,
    margin: 0
  });
  slide.addText((outline.takeaways || model.bullets || []).slice(0, 3).map((item) => `- ${item}`).join("\n"), {
    x: 0.78, y: 5.05, w: 7.75, h: 1.1,
    fontFace: font(input), fontSize: 16, color: p.ink,
    breakLine: false,
    fit: "shrink",
    margin: 0.01,
    breakLine: false
  });

  slide.addText(input.language === "zh" ? "资料状态" : "Research status", {
    x: 10.05, y: 0.86, w: 2.45, h: 0.35,
    fontFace: font(input), fontSize: 14, bold: true, color: "FFFFFF",
    margin: 0
  });
  slide.addText(statusText(input, research), {
    x: 10.05, y: 1.34, w: 2.62, h: 1.7,
    fontFace: font(input), fontSize: 20, bold: true, color: "FFFFFF",
    margin: 0.02,
    fit: "shrink"
  });
  slide.addText(input.language === "zh" ? `生成时间 ${new Date().toLocaleDateString("zh-CN")}` : `Generated ${new Date().toLocaleDateString("en-US")}`, {
    x: 10.05, y: 6.58, w: 2.65, h: 0.32,
    fontFace: font(input), fontSize: 11, color: "FFFFFF",
    margin: 0
  });

  if (input.includeNotes) {
    addNotes(slide, input, model, research);
  }
}

function addContentSlide(pptx, model, input, research, page, total) {
  const slide = pptx.addSlide();
  const p = palette();
  slide.background = { color: p.paper };
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.333, h: 7.5, fill: { color: p.paper }, line: { color: p.paper } });
  addSlideHeader(pptx, slide, model, input, page, total);

  slide.addText(model.insight, {
    x: 0.72, y: 1.24, w: 5.05, h: 1.0,
    fontFace: font(input), fontSize: 23, bold: true, color: p.ink,
    margin: 0.01,
    fit: "shrink"
  });

  const bulletText = model.bullets.slice(0, 5).map((item) => `- ${item}`).join("\n");
  slide.addText(bulletText, {
    x: 0.76, y: 2.55, w: 5.4, h: 3.25,
    fontFace: font(input), fontSize: 17, color: p.ink,
    margin: 0.02,
    breakLine: false,
    fit: "shrink"
  });

  addVisualPanel(pptx, slide, model, input, research);
  addSourceFooter(slide, input, research, model.sourceIndexes, page, total);

  if (input.includeNotes) {
    addNotes(slide, input, model, research);
  }
}

function addSourcesSlide(pptx, model, input, research, page, total) {
  const slide = pptx.addSlide();
  const p = palette();
  slide.background = { color: p.paper };
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.333, h: 7.5, fill: { color: p.paper }, line: { color: p.paper } });
  addSlideHeader(pptx, slide, model, input, page, total);

  const sources = research.results.slice(0, 8);
  if (!sources.length) {
    slide.addText(input.language === "zh" ? "未检索到可引用来源。" : "No citeable online sources were found.", {
      x: 0.78, y: 1.7, w: 10.8, h: 0.6,
      fontFace: font(input), fontSize: 20, color: p.ink
    });
  } else {
    sources.forEach((source, index) => {
      const y = 1.28 + index * 0.63;
      slide.addText(`[${source.id}] ${clip(source.title, 92)}`, {
        x: 0.76, y, w: 10.8, h: 0.26,
        fontFace: font(input), fontSize: 14.5, bold: true, color: p.ink,
        margin: 0
      });
      slide.addText(`${source.domain}  |  ${clip(source.url, 130)}`, {
        x: 0.76, y: y + 0.28, w: 11.4, h: 0.22,
        fontFace: font(input), fontSize: 9.5, color: p.muted,
        margin: 0
      });
    });
  }

  addSourceFooter(slide, input, research, sources.map((source) => source.id), page, total);

  if (input.includeNotes) {
    addNotes(slide, input, model, research);
  }
}

function addSlideHeader(pptx, slide, model, input, page, total) {
  const p = palette();
  slide.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.333, h: 0.16, fill: { color: p.teal }, line: { color: p.teal } });
  slide.addText(model.kicker || "", {
    x: 0.74, y: 0.43, w: 2.8, h: 0.25,
    fontFace: font(input), fontSize: 11, bold: true, color: p.coral,
    margin: 0
  });
  slide.addText(model.title, {
    x: 0.72, y: 0.68, w: 9.6, h: 0.54,
    fontFace: font(input), fontSize: 35, bold: true, color: p.ink,
    margin: 0,
    fit: "shrink"
  });
  slide.addText(`${page}/${total}`, {
    x: 11.77, y: 0.65, w: 0.72, h: 0.28,
    fontFace: font(input), fontSize: 11, color: p.muted,
    align: "right",
    margin: 0
  });
}

function addVisualPanel(pptx, slide, model, input, research) {
  const p = palette();
  slide.addShape(pptx.ShapeType.rect, { x: 6.75, y: 1.22, w: 5.82, h: 4.82, fill: { color: "FFFFFF" }, line: { color: p.line, transparency: 10 }, radius: 0.08 });

  const label = input.language === "zh" ? "分析视图" : "Analytical view";
  slide.addText(label, {
    x: 7.05, y: 1.48, w: 2.4, h: 0.24,
    fontFace: font(input), fontSize: 11, bold: true, color: p.muted,
    margin: 0
  });

  if (/roadmap|actions|策略|执行/i.test(model.visual + model.title)) {
    addRoadmapVisual(pptx, slide, input);
  } else if (/risk|风险/i.test(model.visual + model.title)) {
    addRiskVisual(pptx, slide, input);
  } else if (/evidence|source|来源|证据/i.test(model.visual + model.title)) {
    addEvidenceVisual(pptx, slide, input, research);
  } else {
    addThemeVisual(pptx, slide, input, research);
  }
}

function addThemeVisual(pptx, slide, input, research) {
  const p = palette();
  const themes = research.analysis.themes.slice(0, 5);
  const fallback = input.language === "zh"
    ? [{ term: "趋势", count: 4 }, { term: "机会", count: 3 }, { term: "风险", count: 2 }, { term: "行动", count: 2 }]
    : [{ term: "trends", count: 4 }, { term: "opportunity", count: 3 }, { term: "risk", count: 2 }, { term: "action", count: 2 }];
  const data = themes.length ? themes : fallback;
  const max = Math.max(...data.map((item) => item.count), 1);
  const colors = [p.teal, p.coral, p.gold, p.ink, p.green];

  data.forEach((item, index) => {
    const y = 2.03 + index * 0.67;
    const width = 3.95 * (item.count / max);
    slide.addText(clip(item.term, 18), {
      x: 7.08, y, w: 1.2, h: 0.24,
      fontFace: font(input), fontSize: 11, bold: true, color: p.ink,
      margin: 0
    });
    slide.addShape(pptx.ShapeType.rect, { x: 8.38, y: y + 0.02, w: Math.max(0.28, width), h: 0.22, fill: { color: colors[index % colors.length] }, line: { color: colors[index % colors.length] } });
    slide.addText(String(item.count), {
      x: 12.0, y, w: 0.34, h: 0.22,
      fontFace: font(input), fontSize: 10, color: p.muted,
      align: "right",
      margin: 0
    });
  });

  slide.addText(input.language === "zh" ? "高频主题由标题与摘要抽取，适合作为假设入口。" : "Themes are extracted from titles and snippets as hypothesis inputs.", {
    x: 7.08, y: 5.32, w: 4.95, h: 0.35,
    fontFace: font(input), fontSize: 11, color: p.muted,
    margin: 0,
    fit: "shrink"
  });
}

function addEvidenceVisual(pptx, slide, input, research) {
  const p = palette();
  const domains = research.analysis.topDomains.slice(0, 5);
  const fallback = input.language === "zh"
    ? [{ domain: "待补充来源", count: 1 }]
    : [{ domain: "sources pending", count: 1 }];
  const data = domains.length ? domains : fallback;
  const colors = [p.teal, p.coral, p.gold, p.green, p.ink];

  data.forEach((item, index) => {
    const x = 7.08 + (index % 2) * 2.55;
    const y = 2.02 + Math.floor(index / 2) * 1.04;
    slide.addShape(pptx.ShapeType.rect, { x, y, w: 2.18, h: 0.68, fill: { color: colors[index % colors.length], transparency: 6 }, line: { color: colors[index % colors.length] } });
    slide.addText(String(item.count), {
      x: x + 0.12, y: y + 0.12, w: 0.45, h: 0.24,
      fontFace: font(input), fontSize: 18, bold: true, color: "FFFFFF",
      margin: 0
    });
    slide.addText(clip(item.domain, 24), {
      x: x + 0.62, y: y + 0.16, w: 1.35, h: 0.22,
      fontFace: font(input), fontSize: 10.5, color: "FFFFFF",
      margin: 0,
      fit: "shrink"
    });
  });

  slide.addText(input.language === "zh" ? `证据置信度：${confidenceLabel(research.analysis.confidence, input.language)}` : `Evidence confidence: ${confidenceLabel(research.analysis.confidence, input.language)}`, {
    x: 7.08, y: 5.15, w: 4.85, h: 0.35,
    fontFace: font(input), fontSize: 15, bold: true, color: p.ink,
    margin: 0
  });
}

function addRiskVisual(pptx, slide, input) {
  const p = palette();
  const labels = input.language === "zh"
    ? ["证据质量", "执行复杂度", "外部依赖"]
    : ["Evidence quality", "Execution complexity", "External dependency"];
  const colors = [p.gold, p.coral, p.teal];

  labels.forEach((label, index) => {
    const x = 7.1 + index * 1.65;
    const height = [1.55, 2.35, 1.85][index];
    slide.addShape(pptx.ShapeType.rect, { x, y: 4.58 - height, w: 1.02, h: height, fill: { color: colors[index] }, line: { color: colors[index] } });
    slide.addText(label, {
      x: x - 0.17, y: 4.78, w: 1.35, h: 0.46,
      fontFace: font(input), fontSize: 10.5, bold: true, color: p.ink,
      align: "center",
      margin: 0,
      fit: "shrink"
    });
  });

  slide.addText(input.language === "zh" ? "风险并非否定机会，而是定义验证顺序。" : "Risks define validation order; they do not negate the opportunity.", {
    x: 7.08, y: 5.45, w: 4.75, h: 0.28,
    fontFace: font(input), fontSize: 11.5, color: p.muted,
    margin: 0,
    fit: "shrink"
  });
}

function addRoadmapVisual(pptx, slide, input) {
  const p = palette();
  const labels = input.language === "zh"
    ? ["定义", "验证", "扩展"]
    : ["Define", "Validate", "Scale"];
  const desc = input.language === "zh"
    ? ["问题与指标", "试点与证据", "机制与复盘"]
    : ["Problem and metrics", "Pilots and evidence", "Operating cadence"];
  const colors = [p.teal, p.gold, p.coral];

  labels.forEach((label, index) => {
    const x = 7.08 + index * 1.66;
    slide.addShape(pptx.ShapeType.rect, { x, y: 2.18, w: 1.28, h: 1.28, fill: { color: colors[index] }, line: { color: colors[index] } });
    slide.addText(String(index + 1), {
      x: x + 0.4, y: 2.48, w: 0.48, h: 0.32,
      fontFace: font(input), fontSize: 22, bold: true, color: "FFFFFF",
      align: "center",
      margin: 0
    });
    slide.addText(label, {
      x: x - 0.1, y: 3.72, w: 1.48, h: 0.26,
      fontFace: font(input), fontSize: 13, bold: true, color: p.ink,
      align: "center",
      margin: 0
    });
    slide.addText(desc[index], {
      x: x - 0.18, y: 4.05, w: 1.62, h: 0.35,
      fontFace: font(input), fontSize: 10.2, color: p.muted,
      align: "center",
      margin: 0,
      fit: "shrink"
    });
  });
}

function addSourceFooter(slide, input, research, sourceIndexes, page, total) {
  const p = palette();
  const sourceText = sourceIndexes && sourceIndexes.length
    ? sourceIndexes.map((id) => `[${id}]`).join(" ")
    : (input.language === "zh" ? "来源待补充" : "Sources pending");

  slide.addShape("line", { x: 0.72, y: 6.74, w: 11.85, h: 0, line: { color: p.line, width: 0.75 } });
  slide.addText(sourceText, {
    x: 0.74, y: 6.88, w: 8.1, h: 0.24,
    fontFace: font(input), fontSize: 9.5, color: p.muted,
    margin: 0
  });
  slide.addText(input.language === "zh" ? `公开来源 ${research.results.length} 个` : `${research.results.length} public sources`, {
    x: 9.3, y: 6.88, w: 2.1, h: 0.24,
    fontFace: font(input), fontSize: 9.5, color: p.muted,
    align: "right",
    margin: 0
  });
  slide.addText(`${page}/${total}`, {
    x: 11.65, y: 6.88, w: 0.74, h: 0.24,
    fontFace: font(input), fontSize: 9.5, color: p.muted,
    align: "right",
    margin: 0
  });
}

function addNotes(slide, input, model, research) {
  if (typeof slide.addNotes !== "function") return;
  const sources = (model.sourceIndexes || [])
    .map((id) => research.results.find((result) => result.id === id))
    .filter(Boolean)
    .map((result) => `[${result.id}] ${result.title}: ${result.url}`);
  const notes = [
    model.insight,
    "",
    input.language === "zh" ? "引用来源：" : "Sources:",
    ...(sources.length ? sources : [input.language === "zh" ? "暂无。" : "None."])
  ].join("\n");
  slide.addNotes(notes);
}

function statusText(input, research) {
  const confidence = confidenceLabel(research.analysis.confidence, input.language);
  return input.language === "zh"
    ? `${research.results.length} 个来源\n${confidence} 置信度\n${detectSearchProvider()}`
    : `${research.results.length} sources\n${confidence} confidence\n${detectSearchProvider()}`;
}

function confidenceLabel(value, language) {
  if (language !== "zh") return value;
  return value === "high" ? "高" : value === "medium" ? "中" : "低";
}

function palette() {
  return {
    paper: "F7F7F2",
    ink: "222629",
    charcoal: "2B2F33",
    muted: "66716E",
    line: "D9DED7",
    teal: "1F7A76",
    coral: "D95F43",
    gold: "C49A2C",
    green: "4F7D4A"
  };
}

function font(input) {
  return input.language === "zh" ? "Microsoft YaHei" : "Aptos";
}

function serveStatic(req, res, requestPath) {
  const normalized = requestPath === "/" ? "/index.html" : requestPath;
  const filePath = safeJoin(PUBLIC_DIR, normalized.replace(/^\/+/, ""));
  if (!filePath) return sendJson(res, 403, { error: "Forbidden" });

  fs.readFile(filePath, (error, data) => {
    if (error) return sendJson(res, 404, { error: "Not found" });
    res.writeHead(200, {
      "Content-Type": mimeTypes[path.extname(filePath)] || "application/octet-stream",
      "Cache-Control": "no-store"
    });
    res.end(data);
  });
}

function serveDownload(req, res, fileName) {
  const filePath = safeJoin(OUTPUT_DIR, fileName);
  if (!filePath || path.extname(filePath) !== ".pptx") {
    return sendJson(res, 403, { error: "Forbidden" });
  }

  fs.stat(filePath, (error, stat) => {
    if (error) return sendJson(res, 404, { error: "File not found" });
    res.writeHead(200, {
      "Content-Type": mimeTypes[".pptx"],
      "Content-Length": stat.size,
      "Content-Disposition": `attachment; filename="${path.basename(filePath)}"`
    });
    fs.createReadStream(filePath).pipe(res);
  });
}

function safeJoin(base, target) {
  const resolvedBase = path.resolve(base);
  const resolvedPath = path.resolve(resolvedBase, target);
  if (!resolvedPath.toLowerCase().startsWith(resolvedBase.toLowerCase())) return null;
  return resolvedPath;
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 2_000_000) {
        req.destroy();
        reject(new Error("Request body is too large."));
      }
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(new Error("Invalid JSON body."));
      }
    });
    req.on("error", reject);
  });
}

function readBuffer(req, maxBytes = 25_000_000) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let length = 0;
    req.on("data", (chunk) => {
      length += chunk.length;
      if (length > maxBytes) {
        req.destroy();
        reject(new Error("Upload is too large."));
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function receiveUpload(req) {
  const contentType = req.headers["content-type"] || "";
  const boundaryMatch = contentType.match(/boundary=(?:"([^"]+)"|([^;]+))/i);
  if (!boundaryMatch) {
    throw new Error("Upload boundary is missing.");
  }

  const boundary = boundaryMatch[1] || boundaryMatch[2];
  const body = await readBuffer(req);
  const files = parseMultipartFiles(body, boundary);

  return files.map((file) => {
    const safeName = sanitizeFileName(file.fileName);
    const storedName = `${Date.now().toString(36)}-${crypto.randomBytes(4).toString("hex")}-${safeName}`;
    const outputPath = path.join(UPLOAD_DIR, storedName);
    fs.writeFileSync(outputPath, file.content);
    return {
      originalName: file.fileName,
      storedName,
      size: file.content.length,
      path: outputPath
    };
  });
}

function parseMultipartFiles(body, boundary) {
  const delimiter = Buffer.from(`--${boundary}`);
  const files = [];
  let start = body.indexOf(delimiter);

  while (start !== -1) {
    start += delimiter.length;
    if (body[start] === 45 && body[start + 1] === 45) break;
    if (body[start] === 13 && body[start + 1] === 10) start += 2;

    const headerEnd = body.indexOf(Buffer.from("\r\n\r\n"), start);
    if (headerEnd === -1) break;

    const header = body.slice(start, headerEnd).toString("utf8");
    const next = body.indexOf(delimiter, headerEnd + 4);
    if (next === -1) break;

    const fileNameMatch = header.match(/filename="([^"]*)"/i);
    if (fileNameMatch && fileNameMatch[1]) {
      let contentEnd = next;
      if (body[contentEnd - 2] === 13 && body[contentEnd - 1] === 10) {
        contentEnd -= 2;
      }
      files.push({
        fileName: path.basename(fileNameMatch[1]),
        content: body.slice(headerEnd + 4, contentEnd)
      });
    }

    start = next;
  }

  return files;
}

function sanitizeFileName(value) {
  const name = path.basename(String(value || "upload.bin")).replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").trim();
  return name || "upload.bin";
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(JSON.stringify(payload, null, 2));
}

function dedupeResults(results) {
  const seen = new Set();
  const output = [];
  for (const result of results) {
    const url = normalizeUrl(result.url);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    output.push({
      title: cleanText(result.title || ""),
      url,
      snippet: cleanText(result.snippet || ""),
      provider: result.provider || "search"
    });
  }
  return output;
}

function normalizeUrl(url) {
  try {
    const parsed = new URL(url);
    parsed.hash = "";
    return parsed.toString();
  } catch (_) {
    return "";
  }
}

function normalizeDuckDuckGoUrl(href) {
  try {
    const url = href.startsWith("//") ? `https:${href}` : href;
    const parsed = new URL(url);
    const uddg = parsed.searchParams.get("uddg");
    return uddg ? decodeURIComponent(uddg) : url;
  } catch (_) {
    return href;
  }
}

function getDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return "";
  }
}

function cleanText(html) {
  return decodeHtml(String(html || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}

function decodeHtml(value) {
  return String(value || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

function countBy(items) {
  return items.reduce((map, item) => {
    map[item] = (map[item] || 0) + 1;
    return map;
  }, {});
}

function ensureArray(value) {
  return Array.isArray(value) ? value : [];
}

function clip(value, max) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trim()}…`;
}

function clamp(value, min, max) {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function slugify(value) {
  const ascii = String(value)
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .toLowerCase();
  return ascii || crypto.createHash("sha1").update(String(value)).digest("hex").slice(0, 10);
}
