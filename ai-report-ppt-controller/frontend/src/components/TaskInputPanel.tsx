import type { FormEvent } from "react";

export interface TaskFormState {
  title: string;
  task_type: string;
  language: string;
  domain: string;
  audience: string;
  ppt_topic: string;
  ppt_pages: string;
  word_topic: string;
  word_target_words: string;
  keywords: string;
  region: string;
  time_range: string;
  database_scope: string;
  search_boundary: string;
  user_outline: string;
  main_agent: string;
  review_agent: string;
  loop_rounds: string;
  enable_web_search: boolean;
  enable_patent_search: boolean;
  enable_paper_search: boolean;
  enable_industry_search: boolean;
  enable_cross_review: boolean;
  enable_fact_check: boolean;
  enable_format_check: boolean;
  enable_professional_review: boolean;
}

interface Props {
  value: TaskFormState;
  onChange: (field: keyof TaskFormState, value: string | boolean) => void;
  onCreate: () => void;
  onRun: () => void;
  onClear: () => void;
  onSaveDraft: () => void;
}

export function TaskInputPanel({
  value,
  onChange,
  onCreate,
  onRun,
  onClear,
  onSaveDraft
}: Props) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onCreate();
  }

  const showPpt = value.task_type === "ppt" || value.task_type === "ppt_word";
  const showWord = value.task_type === "word" || value.task_type === "ppt_word";

  return (
    <aside className="left-panel">
      <form onSubmit={submit} className="form-stack">
        <section className="group">
          <div className="group-title">
            <h2>任务目标</h2>
            <button className="link-button" type="button" onClick={onClear}>清空表单 / 新建任务</button>
          </div>
          <label className="field">
            <span>任务标题 <b>*</b></span>
            <input
              name="title"
              value={value.title}
              placeholder="请输入任务标题，例如：GaN功率器件专利态势分析"
              onChange={(event) => onChange("title", event.target.value)}
            />
          </label>
          <div className="grid-2">
            <label className="field">
              <span>输出类型</span>
              <select value={value.task_type} onChange={(event) => onChange("task_type", event.target.value)}>
                <option value="ppt">PPT</option>
                <option value="word">Word报告</option>
                <option value="ppt_word">PPT+Word</option>
                <option value="research_only">仅资料检索</option>
                <option value="outline_only">仅大纲生成</option>
              </select>
            </label>
            <label className="field">
              <span>语言</span>
              <select value={value.language} onChange={(event) => onChange("language", event.target.value)}>
                <option value="中文">中文</option>
                <option value="英文">英文</option>
                <option value="中英双语">中英双语</option>
              </select>
            </label>
          </div>
          <div className="grid-2">
            <label className="field">
              <span>研究领域</span>
              <input value={value.domain} placeholder="请选择或输入研究领域" onChange={(event) => onChange("domain", event.target.value)} />
            </label>
            <label className="field">
              <span>目标受众</span>
              <input value={value.audience} placeholder="例如：企业技术部门、投资人、政策部门" onChange={(event) => onChange("audience", event.target.value)} />
            </label>
          </div>
          <details className="advanced-title">
            <summary>高级标题设置</summary>
            <label className="field">
              <span>PPT主题</span>
              <input value={value.ppt_topic} placeholder="默认跟随任务标题" onChange={(event) => onChange("ppt_topic", event.target.value)} />
            </label>
            <label className="field">
              <span>Word报告标题</span>
              <input value={value.word_topic} placeholder="默认跟随任务标题" onChange={(event) => onChange("word_topic", event.target.value)} />
            </label>
          </details>
        </section>

        <section className="group">
          <h2>输出配置</h2>
          <div className="grid-2">
            {showPpt ? (
              <label className="field">
                <span>PPT页数</span>
                <input value={value.ppt_pages} type="number" min="5" max="80" placeholder="例如：20" onChange={(event) => onChange("ppt_pages", event.target.value)} />
              </label>
            ) : null}
            {showWord ? (
              <label className="field">
                <span>Word字数</span>
                <input value={value.word_target_words} type="number" min="1000" max="80000" placeholder="例如：8000" onChange={(event) => onChange("word_target_words", event.target.value)} />
              </label>
            ) : null}
          </div>
        </section>

        <section className="group">
          <h2>检索策略</h2>
          <label className="field">
            <span>关键词</span>
            <input value={value.keywords} placeholder="输入关键词，多个关键词可用逗号分隔" onChange={(event) => onChange("keywords", event.target.value)} />
          </label>
          <div className="grid-2">
            <label className="field"><span>地区</span><input value={value.region} placeholder="输入地区或市场范围" onChange={(event) => onChange("region", event.target.value)} /></label>
            <label className="field"><span>时间范围</span><input value={value.time_range} placeholder="例如：近五年、2020-2026" onChange={(event) => onChange("time_range", event.target.value)} /></label>
          </div>
          <label className="field">
            <span>数据源范围</span>
            <input value={value.database_scope} placeholder="例如：公开网络、专利、论文、企业官网" onChange={(event) => onChange("database_scope", event.target.value)} />
          </label>
          <div className="check-grid">
            <label className="check-field"><input type="checkbox" checked={value.enable_web_search} onChange={(event) => onChange("enable_web_search", event.target.checked)} /><span>公开网络</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_patent_search} onChange={(event) => onChange("enable_patent_search", event.target.checked)} /><span>专利</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_paper_search} onChange={(event) => onChange("enable_paper_search", event.target.checked)} /><span>论文</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_industry_search} onChange={(event) => onChange("enable_industry_search", event.target.checked)} /><span>产业信息</span></label>
          </div>
          <label className="field">
            <span>章节结构</span>
            <textarea value={value.user_outline} rows={5} placeholder="可选。请输入自定义章节结构，留空则由 Agent 生成。" onChange={(event) => onChange("user_outline", event.target.value)} />
          </label>
          <label className="field">
            <span>补充要求</span>
            <textarea value={value.search_boundary} rows={4} placeholder="请输入重点关注方向、排除范围、数据源要求等" onChange={(event) => onChange("search_boundary", event.target.value)} />
          </label>
        </section>

        <details className="group advanced-config">
          <summary>高级配置</summary>
          <div className="grid-2">
            <label className="field">
              <span>主 Agent</span>
              <select value={value.main_agent} onChange={(event) => onChange("main_agent", event.target.value)}>
                <option value="auto">Auto</option>
                <option value="hermes">Hermes</option>
                <option value="codex">Codex</option>
              </select>
            </label>
            <label className="field">
              <span>审核 Agent</span>
              <select value={value.review_agent} onChange={(event) => onChange("review_agent", event.target.value)}>
                <option value="auto">Auto</option>
                <option value="hermes">Hermes</option>
                <option value="codex">Codex</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>Loop 轮数</span>
            <input value={value.loop_rounds} type="number" min="1" max="5" onChange={(event) => onChange("loop_rounds", event.target.value)} />
          </label>
          <div className="grid-2">
            <label className="field"><span>Chrome CDP 端口</span><input value="127.0.0.1:9222" readOnly /></label>
            <label className="field"><span>输出目录</span><input value="运行时生成" readOnly /></label>
          </div>
          <div className="check-grid">
            <label className="check-field"><input type="checkbox" checked={value.enable_cross_review} onChange={(event) => onChange("enable_cross_review", event.target.checked)} /><span>多轮互审</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_fact_check} onChange={(event) => onChange("enable_fact_check", event.target.checked)} /><span>事实核查</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_format_check} onChange={(event) => onChange("enable_format_check", event.target.checked)} /><span>格式审查</span></label>
            <label className="check-field"><input type="checkbox" checked={value.enable_professional_review} onChange={(event) => onChange("enable_professional_review", event.target.checked)} /><span>专业审查</span></label>
          </div>
        </details>

        <div className="button-grid">
          <button type="button" onClick={onSaveDraft}>保存草稿</button>
          <button type="submit">创建任务</button>
        </div>
        <button className="primary" type="button" onClick={onRun}>开始运行 Multi-agent 工作流</button>
      </form>
    </aside>
  );
}
