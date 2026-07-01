type CheckResult = {
  name?: string;
  ok?: boolean;
  status?: string;
  detail?: string;
};

export function ConnectionStatusCard({ checks }: { checks: Record<string, unknown> }) {
  const items = Object.entries(checks) as [string, CheckResult][];

  return (
    <section className="status-card">
      <h2>系统状态</h2>
      <div className="status-list">
        {items.length === 0 ? <p>尚未检测连接。</p> : null}
        {items.map(([key, value]) => (
          <div className="status-item" key={key}>
            <div>
              <strong>{value.name || key}</strong>
              <p>{value.detail || value.status || "无详情"}</p>
            </div>
            <span className={`badge ${value.ok ? "success" : "failed"}`}>{value.status || "unknown"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
