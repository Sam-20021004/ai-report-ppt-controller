export function AgentLogViewer({ log }: { log: unknown }) {
  return <pre className="terminal tall">{JSON.stringify(log, null, 2)}</pre>;
}
