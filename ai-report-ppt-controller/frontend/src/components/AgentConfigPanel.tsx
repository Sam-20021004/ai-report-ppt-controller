export function AgentConfigPanel() {
  return (
    <section className="group">
      <h2>Agent 配置</h2>
      <select defaultValue="auto">
        <option>auto</option>
        <option>hermes</option>
        <option>codex</option>
      </select>
    </section>
  );
}
