import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const APP_JS = new URL("./app.js", import.meta.url);

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  toggle(name, force) {
    if (force === undefined ? !this.values.has(name) : force) {
      this.values.add(name);
      return true;
    }
    this.values.delete(name);
    return false;
  }

  contains(name) {
    return this.values.has(name);
  }
}

class FakeElement {
  constructor(selector = "") {
    this.selector = selector;
    this.children = [];
    this.classList = new FakeClassList();
    this.dataset = {};
    this.files = [];
    this.value = "";
    this.checked = false;
    this.type = "text";
    this.textContent = "";
    this.innerHTML = "";
  }

  addEventListener() {}

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  insertAdjacentElement() {}

  querySelector(selector) {
    return this.ownerDocument.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.ownerDocument.querySelectorAll(selector);
  }

  closest() {
    return this;
  }

  reset() {
    if (!this.elements) return;
    Object.values(this.elements).forEach((element) => {
      if (element.type === "checkbox") {
        element.checked = false;
      } else {
        element.value = "";
      }
    });
  }
}

function field(value = "", type = "text") {
  const element = new FakeElement();
  element.value = value;
  element.type = type;
  return element;
}

function createFakeDocument() {
  const elements = new Map();
  const document = {
    activeElement: null,
    createElement(tagName) {
      const element = new FakeElement(tagName);
      element.ownerDocument = document;
      return element;
    },
    querySelector(selector) {
      if (!elements.has(selector)) {
        const element = new FakeElement(selector);
        element.ownerDocument = document;
        elements.set(selector, element);
      }
      return elements.get(selector);
    },
    querySelectorAll(selector) {
      if (selector === ".tab") return [];
      if (selector === ".example-card") return [];
      if (selector === "details") return [];
      if (selector === "input[type='file']") {
        return [document.querySelector("#ppt-template"), document.querySelector("#word-template")];
      }
      if (selector === "[name='ppt_topic'], [name='word_topic']") {
        return [form.elements.ppt_topic, form.elements.word_topic];
      }
      if (selector === ".ppt-only" || selector === ".word-only") return [new FakeElement(selector)];
      return [];
    },
    getElementById(id) {
      return document.querySelector(`#${id}`);
    },
  };

  const form = document.querySelector("#task-form");
  form.elements = {
    title: field(""),
    task_type: field("ppt"),
    domain: field(""),
    audience: field(""),
    language: field("中文"),
    ppt_topic: field(""),
    ppt_pages: field(""),
    word_topic: field(""),
    word_target_words: field(""),
    keywords: field(""),
    region: field(""),
    time_range: field(""),
    database_scope: field(""),
    search_boundary: field(""),
    user_outline: field(""),
    loop_rounds: field("1"),
    main_agent: field("auto"),
    review_agent: field("auto"),
    preserve_ppt_template: field("", "checkbox"),
    auto_charts: field("", "checkbox"),
    insert_citations: field("", "checkbox"),
    generate_speaker_notes: field("", "checkbox"),
    enable_web_search: field("", "checkbox"),
    enable_paper_search: field("", "checkbox"),
    enable_patent_search: field("", "checkbox"),
    enable_industry_search: field("", "checkbox"),
    enable_cross_review: field("", "checkbox"),
    enable_fact_check: field("", "checkbox"),
    enable_format_check: field("", "checkbox"),
    enable_professional_review: field("", "checkbox"),
  };

  Object.values(form.elements).forEach((element) => {
    element.ownerDocument = document;
  });

  document.querySelector("#ppt-template").files = [];
  document.querySelector("#word-template").files = [];

  return document;
}

class FakeFormData {
  constructor(form) {
    this.form = form;
  }

  get(name) {
    const element = this.form.elements[name];
    if (!element) return null;
    if (element.type === "checkbox") return element.checked ? "on" : null;
    return element.value;
  }
}

function createStorage(initialEntries) {
  const values = new Map(Object.entries(initialEntries));
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function jsonResponse(data, ok = true) {
  return {
    ok,
    json: async () => data,
  };
}

test("initialization restores the saved current task after browser reload", async () => {
  const fetchCalls = [];
  const document = createFakeDocument();
  const localStorage = createStorage({
    ai_report_current_task_id: "task-restore-1",
  });

  const context = vm.createContext({
    console,
    document,
    FormData: FakeFormData,
    localStorage,
    setTimeout,
    clearTimeout,
    fetch: async (path) => {
      fetchCalls.push(path);
      if (path === "/api/health") {
        return jsonResponse({ ok: true, phase: "test", storage: { writable: true } });
      }
      if (path === "/api/task/task-restore-1") {
        return jsonResponse({
          task_id: "task-restore-1",
          status: "completed",
          request: { title: "Reload restore smoke" },
          steps: [],
          phase2_outputs_summary: { phase2_research_summary: "ok" },
          phase2_errors: [],
        });
      }
      if (path === "/api/task/task-restore-1/files") {
        return jsonResponse({ task_id: "task-restore-1", files: [] });
      }
      if (path === "/api/task/task-restore-1/phase2/audit") {
        return jsonResponse({
          available: true,
          source_count: 1,
          real_url_count: 1,
          manual_review_count: 1,
          review_summary: {
            total: 1,
            unreviewed: 0,
            approved: 1,
            rejected: 0,
            needs_followup: 0,
          },
          sources: [
            {
              source_id: "S1",
              source_key: "s1",
              title: "Reviewed source",
              url: "https://example.com/source",
              review_status: "approved",
              review_note: "phase2.11 reload restore smoke note",
            },
          ],
        });
      }
      return jsonResponse({ error: `unexpected ${path}` }, false);
    },
    window: {
      setInterval: () => 1,
      clearInterval: () => {},
    },
  });

  context.window.window = context.window;
  context.window.document = document;
  context.window.localStorage = localStorage;

  vm.runInContext(readFileSync(APP_JS, "utf8"), context);
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(fetchCalls.filter((path) => path.startsWith("/api/task/task-restore-1")), [
    "/api/task/task-restore-1",
    "/api/task/task-restore-1/files",
    "/api/task/task-restore-1/phase2/audit",
  ]);
  assert.equal(document.querySelector("#current-task").textContent, "Reload restore smoke (task-restore-1)");
  assert.match(document.querySelector("#phase2-audit").innerHTML, /phase2\.11 reload restore smoke note/);
  assert.match(document.querySelector("#phase2-audit").innerHTML, /approved/);
});
